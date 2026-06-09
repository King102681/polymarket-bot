"""用便宜 LLM（Haiku）評估（趨勢, 候選市場）並產生 dry-run 訂單建議。

對每個趨勢＋其 top-K 候選市場，呼叫一次 LLM：
  - 從候選裡挑出真正對應的市場（或都不相關 → 不下注）
  - 判斷話題新資訊支持買 YES/NO（或無法判斷方向 → 不下注）
  - 給 confidence
這同時解決「規則情緒判不出方向」與「關鍵字亂配市場」兩個問題。

無 ANTHROPIC_API_KEY 或 API 失敗時優雅降級（記錄並拒絕，不崩潰，pipeline 維持綠燈）。

輸出（與鯨魚策略分開）：
  data/pending_orders_trend.jsonl
  data/rejected_trend.jsonl
  data/processed_trend.json
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from core import config
from core.polymarket_client import PolymarketClient
from trend_trade import llm
from trend_trade.market_matcher import _hours_until, _parse_json_list
from trend_trade.trend_fetcher import TrendItem

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_PENDING_PATH = _DATA_DIR / "pending_orders_trend.jsonl"
_REJECTED_PATH = _DATA_DIR / "rejected_trend.jsonl"
_PROCESSED_PATH = _DATA_DIR / "processed_trend.json"

SLIPPAGE_BUFFER = 0.005
MIN_BET_USDC = 1.0

_EVAL_SCHEMA = {
    "type": "object",
    "properties": {
        "market_index": {"type": "integer"},
        "side": {"type": "string", "enum": ["YES", "NO", "NONE"]},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
    },
    "required": ["market_index", "side", "confidence", "reasoning"],
    "additionalProperties": False,
}

_EVAL_SYSTEM = (
    "你是 Polymarket 預測市場交易員。核心假設：社群媒體的熱度與情緒，在某些事件上會"
    "『領先』市場定價 30–120 分鐘；目標是在市場還沒反應的窗口進場。\n\n"
    "輸入是一條中文或英文熱門話題，以及數個候選的二元（Yes/No）市場（含目前 Yes 機率）。\n"
    "請做三件事：\n"
    "1. market_index：從候選裡挑出『真正對應這條話題』的那一個。若沒有任何一個真的相關，回 -1。\n"
    "2. side：這條話題的新資訊支持買哪一邊（YES 或 NO）。若話題沒提供可判斷方向的新資訊、"
    "或資訊明顯已被市場 price-in，回 NONE。\n"
    "3. confidence：0–1，你對『方向正確且市場尚未充分反應』的把握。\n\n"
    "嚴格要求：寧可錯過，不可亂下。只有當話題情緒方向與當前定價有明顯落差、且很可能很快被"
    "市場修正時，才給較高 confidence。reasoning 用中文簡述。只回傳 JSON。"
)


@dataclass
class TrendOrder:
    strategy: str
    trend_id: str
    detected_at: int
    trend_title: str
    trend_heat: float
    platforms: str
    market_title: str
    condition_id: str
    asset: str
    outcome: str
    outcome_index: int
    market_price: float
    suggested_price: float
    suggested_size: float
    suggested_cost_usdc: float
    confidence: float
    market_end_iso: str
    reasoning: str
    notes: str


@dataclass
class TrendRejected:
    strategy: str
    trend_id: str
    trend_title: str
    market_title: str
    reason: str


def _load_processed() -> set[str]:
    if not _PROCESSED_PATH.exists():
        return set()
    try:
        return set(json.loads(_PROCESSED_PATH.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _save_processed(hashes: set[str]) -> None:
    _PROCESSED_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PROCESSED_PATH.write_text(json.dumps(sorted(hashes)), encoding="utf-8")


def _append(path: Path, items: list) -> None:
    if not items:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for x in items:
            f.write(json.dumps(asdict(x), ensure_ascii=False) + "\n")


def _best_ask(book) -> tuple[float, float] | None:
    asks = getattr(book, "asks", None)
    if asks is None and isinstance(book, dict):
        asks = book.get("asks")
    if not asks:
        return None
    a0 = asks[0]
    try:
        price = float(getattr(a0, "price", None) or a0.get("price"))
        size = float(getattr(a0, "size", None) or a0.get("size"))
    except Exception:
        return None
    return price, size


def _yes_prob(market: dict) -> str:
    """取市場 Yes 的當前機率字串，給 LLM 當定價參考。"""
    outcomes = _parse_json_list(market.get("outcomes"))
    prices = _parse_json_list(market.get("outcomePrices"))
    for i, o in enumerate(outcomes):
        if str(o).upper() == "YES" and i < len(prices):
            try:
                return f"{float(prices[i]):.2f}"
            except Exception:
                return str(prices[i])
    return "?"


def _ask_llm(tr: TrendItem, candidates: list[dict]) -> dict | None:
    lines = []
    for i, m in enumerate(candidates):
        q = str(m.get("question") or m.get("slug") or "")[:120]
        lines.append(f"[{i}] {q}  (Yes={_yes_prob(m)})")
    user = (
        f"熱門話題：{tr.title}\n"
        f"來源：{', '.join(tr.platforms)}；熱度 {tr.heat}/100\n\n"
        f"候選市場：\n" + "\n".join(lines)
    )
    return llm.call_json(
        model=config.TREND_EVALUATOR_MODEL,
        system=_EVAL_SYSTEM,
        user=user,
        schema=_EVAL_SCHEMA,
        max_tokens=512,
    )


def evaluate(
    pairs: list[tuple[TrendItem, list[dict]]],
    client: PolymarketClient | None = None,
) -> tuple[list[TrendOrder], list[TrendRejected]]:
    """用 LLM 評估每個趨勢＋其候選市場；無 key/失敗時優雅降級成拒絕。"""
    client = client or PolymarketClient()
    processed = _load_processed()
    orders: list[TrendOrder] = []
    rejected: list[TrendRejected] = []

    for tr, candidates in pairs:
        if tr.id in processed:
            continue
        processed.add(tr.id)

        def rej(reason: str, mkt_title: str = "") -> None:
            rejected.append(TrendRejected(
                strategy="trend", trend_id=tr.id,
                trend_title=tr.title, market_title=mkt_title[:80], reason=reason,
            ))

        if not candidates:
            rej("無候選市場")
            continue

        res = _ask_llm(tr, candidates)
        if not res:
            rej("LLM 無回應（檢查 ANTHROPIC_API_KEY）")
            continue

        try:
            idx = int(res.get("market_index", -1))
            conf = max(0.0, min(1.0, float(res.get("confidence", 0))))
        except Exception:
            rej("LLM 回傳格式異常")
            continue
        side = str(res.get("side", "NONE")).upper()
        reasoning = str(res.get("reasoning", ""))

        if idx < 0 or idx >= len(candidates) or side == "NONE":
            rej(f"LLM 判定不下注：{reasoning[:60]}")
            continue
        if conf < config.TREND_MIN_CONFIDENCE:
            rej(f"信心 {conf:.2f} < {config.TREND_MIN_CONFIDENCE}：{reasoning[:40]}")
            continue

        market = candidates[idx]
        title = str(market.get("question") or market.get("slug") or "")
        cid = str(market.get("conditionId") or market.get("condition_id") or "")
        outcomes = _parse_json_list(market.get("outcomes"))
        prices = _parse_json_list(market.get("outcomePrices"))
        tok_ids = _parse_json_list(market.get("clobTokenIds"))
        hours_left = _hours_until(market)

        if len(outcomes) != 2 or len(tok_ids) != 2:
            rej("非標準二元市場", title)
            continue
        if hours_left < config.TREND_MIN_HOURS_LEFT:
            rej(f"距結算 {hours_left:.0f}h < {config.TREND_MIN_HOURS_LEFT:.0f}h", title)
            continue

        outcome_index = next(
            (i for i, o in enumerate(outcomes) if str(o).upper() == side), -1
        )
        if outcome_index < 0:
            rej(f"side {side} 不在 outcomes {outcomes}", title)
            continue
        token_id = str(tok_ids[outcome_index])

        try:
            book = client.get_orderbook(token_id)
        except Exception as e:
            rej(f"orderbook 失敗：{type(e).__name__}", title)
            continue
        ba = _best_ask(book)
        if ba is None:
            rej("訂單簿無 asks", title)
            continue
        best_ask_price, best_ask_size = ba

        suggested_price = round(min(best_ask_price * (1 + SLIPPAGE_BUFFER), 0.999), 4)
        if not (config.TREND_MIN_ENTRY_PRICE <= suggested_price <= config.TREND_MAX_ENTRY_PRICE):
            rej(f"進場價 {suggested_price:.3f} 不在 "
                f"[{config.TREND_MIN_ENTRY_PRICE}, {config.TREND_MAX_ENTRY_PRICE}]", title)
            continue

        target_usdc = max(MIN_BET_USDC, min(config.MAX_BET_USDC, config.MAX_BET_USDC * conf))
        suggested_size = round(target_usdc / suggested_price, 2)
        actual_cost = round(suggested_size * suggested_price, 2)

        try:
            mid = float(prices[outcome_index])
        except Exception:
            mid = 0.0

        notes = ""
        if best_ask_size < suggested_size:
            notes = f"⚠️ ask size {best_ask_size:.0f} < 需要 {suggested_size:.0f}"

        orders.append(TrendOrder(
            strategy="trend", trend_id=tr.id, detected_at=int(time.time()),
            trend_title=tr.title, trend_heat=tr.heat,
            platforms=",".join(tr.platforms),
            market_title=title[:120], condition_id=cid, asset=token_id,
            outcome=str(outcomes[outcome_index]), outcome_index=outcome_index,
            market_price=mid, suggested_price=suggested_price,
            suggested_size=suggested_size, suggested_cost_usdc=actual_cost,
            confidence=conf, market_end_iso=str(market.get("endDate") or ""),
            reasoning=reasoning, notes=notes,
        ))
        print(f"   ✅ {side} @ {suggested_price:.3f}  信心={conf:.2f}  {title[:50]}")

    _append(_PENDING_PATH, orders)
    _append(_REJECTED_PATH, rejected)
    _save_processed(processed)
    print(f"\n  ✅ trend 通過: {len(orders)}  ❌ 拒絕: {len(rejected)}")
    return orders, rejected
