"""由 Claude 判斷某個 (趨勢, 市場) 是否值得下注，並產生 dry-run 訂單建議。

獨立輸出檔（與鯨魚策略分開，便於最後比較績效）：
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
        "should_bet": {"type": "boolean"},
        "side": {"type": "string", "enum": ["YES", "NO", "NONE"]},
        "confidence": {"type": "number"},
        "suggested_ratio": {"type": "number"},
        "reasoning": {"type": "string"},
    },
    "required": ["should_bet", "side", "confidence", "suggested_ratio", "reasoning"],
    "additionalProperties": False,
}

_EVAL_SYSTEM = (
    "你是 Polymarket 預測市場交易員。核心假設：社群媒體熱度與情緒，"
    "在某些事件上會『領先』市場定價 30–120 分鐘；要在市場還沒反應的窗口進場。\n\n"
    "給你一條熱門話題與一個對應的二元市場（含當前賠率），判斷是否下注。\n"
    "嚴格要求：\n"
    "- 只有當『話題情緒方向』與『當前市場定價』有明顯落差、且該落差可能很快被"
    "市場修正時，才下注。資訊若已被市場 price-in → 不下注。\n"
    "- 若不確定話題與市場是否真的對應 → 不下注。\n"
    "- side 用 YES/NO 表示你認為被低估、應買進的那一邊；不下注用 NONE。\n"
    "- confidence 0–1；suggested_ratio 0–1（佔單筆上限的比例，越有把握越高）。\n"
    "- 寧可錯過，不可亂下。reasoning 用中文簡述理由。只回傳 JSON。"
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
    asset: str            # CLOB token id
    outcome: str          # "Yes" / "No"
    outcome_index: int
    market_price: float   # 進場前 mid（參考）
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


def evaluate(
    pairs: list[tuple[TrendItem, dict]], client: PolymarketClient | None = None
) -> tuple[list[TrendOrder], list[TrendRejected]]:
    client = client or PolymarketClient()
    processed = _load_processed()
    orders: list[TrendOrder] = []
    rejected: list[TrendRejected] = []

    for tr, market in pairs:
        cid = str(market.get("conditionId") or market.get("condition_id"))
        h = f"{tr.id}:{cid}"
        if h in processed:
            continue
        processed.add(h)

        title = str(market.get("question") or market.get("slug") or "")
        outcomes = _parse_json_list(market.get("outcomes"))
        prices = _parse_json_list(market.get("outcomePrices"))
        token_ids = _parse_json_list(market.get("clobTokenIds"))
        hours_left = _hours_until(market)

        def rej(reason: str) -> None:
            rejected.append(TrendRejected(
                strategy="trend", trend_id=tr.id, trend_title=tr.title,
                market_title=title[:80], reason=reason,
            ))

        if len(outcomes) != 2 or len(token_ids) != 2:
            rej("非標準二元市場")
            continue
        if hours_left < config.TREND_MIN_HOURS_LEFT:
            rej(f"距結算 {hours_left:.0f}h < {config.TREND_MIN_HOURS_LEFT:.0f}h")
            continue

        odds = "; ".join(
            f"{o}={prices[i] if i < len(prices) else '?'}"
            for i, o in enumerate(outcomes)
        )
        user = (
            f"熱門話題：{tr.title}\n"
            f"來源：{', '.join(tr.platforms)}；熱度 {tr.heat}/100；"
            f"追蹤 {tr.minutes_tracked} 分鐘；排名上升：{'是' if tr.rank_improved else '否'}\n\n"
            f"市場：{title}\n"
            f"當前賠率：{odds}\n"
            f"距結算：{hours_left:.0f} 小時"
        )
        res = llm.call_json(
            model=config.TREND_EVALUATOR_MODEL,
            system=_EVAL_SYSTEM, user=user, schema=_EVAL_SCHEMA, max_tokens=1024,
        )
        if not res:
            rej("Claude 無回應")
            continue
        if not res.get("should_bet") or str(res.get("side")).upper() == "NONE":
            rej(f"Claude 判定不下注：{str(res.get('reasoning', ''))[:50]}")
            continue

        conf = max(0.0, min(1.0, float(res.get("confidence", 0))))
        if conf < config.TREND_MIN_CONFIDENCE:
            rej(f"信心 {conf:.2f} < {config.TREND_MIN_CONFIDENCE}")
            continue

        side = str(res.get("side", "")).upper()
        outcome_index = next(
            (i for i, o in enumerate(outcomes) if str(o).upper() == side), -1
        )
        if outcome_index < 0:
            rej(f"side {side} 不在 outcomes {outcomes}")
            continue
        token_id = str(token_ids[outcome_index])

        try:
            book = client.get_orderbook(token_id)
        except Exception as e:
            rej(f"orderbook 失敗：{type(e).__name__}")
            continue
        ba = _best_ask(book)
        if ba is None:
            rej("訂單簿無 asks")
            continue
        best_ask_price, best_ask_size = ba

        suggested_price = round(min(best_ask_price * (1 + SLIPPAGE_BUFFER), 0.999), 4)
        if not (config.TREND_MIN_ENTRY_PRICE <= suggested_price <= config.TREND_MAX_ENTRY_PRICE):
            rej(f"進場價 {suggested_price:.3f} 不在 "
                f"[{config.TREND_MIN_ENTRY_PRICE}, {config.TREND_MAX_ENTRY_PRICE}]")
            continue

        ratio = max(0.0, min(1.0, float(res.get("suggested_ratio", 0))))
        target_usdc = max(MIN_BET_USDC, min(config.MAX_BET_USDC, config.MAX_BET_USDC * ratio))
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
            reasoning=str(res.get("reasoning", "")), notes=notes,
        ))

    _append(_PENDING_PATH, orders)
    _append(_REJECTED_PATH, rejected)
    _save_processed(processed)
    print(f"\n  ✅ 通過: {len(orders)}  ❌ 拒絕: {len(rejected)}")
    return orders, rejected
