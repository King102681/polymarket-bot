"""規則式評估（趨勢, 市場）是否值得下注（免 API 版）。

替代原本的 Claude Opus 評估，改用：
  - 情緒關鍵字偵測（正面 → YES，負面 → NO）
  - 熱度 × 情緒強度 → 信心分數
  - 多平台出現加分、排名上升加分

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
from trend_trade.market_matcher import _hours_until, _parse_json_list
from trend_trade.trend_fetcher import TrendItem

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_PENDING_PATH = _DATA_DIR / "pending_orders_trend.jsonl"
_REJECTED_PATH = _DATA_DIR / "rejected_trend.jsonl"
_PROCESSED_PATH = _DATA_DIR / "processed_trend.json"

SLIPPAGE_BUFFER = 0.005
MIN_BET_USDC    = 1.0

# ── 情緒關鍵字 ──────────────────────────────────────────────────────────────
# 正向：暗示事情會「成功/發生/通過」→ 買 YES
_POS: list[str] = [
    "通過", "批准", "協議", "簽署", "達成", "成功", "確認", "同意",
    "支持", "停火", "和平", "撤軍", "解除", "正式", "落實",
    "上漲", "突破", "創高", "升值", "回升", "反彈",
    "當選", "勝選", "連任", "獲勝",
]
# 負向：暗示事情「不會發生/失敗/惡化」→ 買 NO
_NEG: list[str] = [
    "失敗", "崩潰", "拒絕", "否決", "撤回", "取消", "流產",
    "制裁", "開戰", "宣戰", "升級", "衝突", "打擊", "空襲",
    "下跌", "暴跌", "崩盤", "危機", "違約", "破產",
    "落敗", "敗選", "下台", "辭職", "彈劾",
]


def _sentiment(title: str) -> tuple[str, float]:
    """
    回傳 (side, strength)。
    side: "YES" / "NO" / ""
    strength: 0.0-1.0（情緒明確程度）
    """
    pos_hits = sum(1 for w in _POS if w in title)
    neg_hits = sum(1 for w in _NEG if w in title)
    total = pos_hits + neg_hits
    if total == 0:
        return "", 0.0
    if pos_hits > neg_hits:
        return "YES", min(1.0, pos_hits / max(total, 2))
    if neg_hits > pos_hits:
        return "NO", min(1.0, neg_hits / max(total, 2))
    return "", 0.0   # 平手 → 不確定


def _confidence(tr: TrendItem, sentiment_strength: float) -> float:
    """
    綜合熱度、情緒強度、多平台、排名上升，算出 0-1 信心值。
    """
    heat_norm = tr.heat / 100.0                    # 0-1
    freq_bonus = min(tr.frequency / 3, 1.0) * 0.1  # 多平台 +10%
    rise_bonus = 0.05 if tr.rank_improved else 0.0  # 排名上升 +5%
    # 追蹤夠久（≥30分鐘）代表話題持續，+5%
    dur_bonus = 0.05 if tr.minutes_tracked >= 30 else 0.0

    raw = (heat_norm * 0.5
           + sentiment_strength * 0.35
           + freq_bonus + rise_bonus + dur_bonus)
    return round(min(1.0, raw), 3)


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
        size  = float(getattr(a0, "size",  None) or a0.get("size"))
    except Exception:
        return None
    return price, size


def evaluate(
    pairs: list[tuple[TrendItem, dict]],
    client: PolymarketClient | None = None,
) -> tuple[list[TrendOrder], list[TrendRejected]]:
    """規則式評估每個 (趨勢, 市場) 對，不需要 AI API。"""
    client = client or PolymarketClient()
    processed = _load_processed()
    orders:   list[TrendOrder]    = []
    rejected: list[TrendRejected] = []

    for tr, market in pairs:
        cid = str(market.get("conditionId") or market.get("condition_id") or "")
        h = f"{tr.id}:{cid}"
        if h in processed:
            continue
        processed.add(h)

        title    = str(market.get("question") or market.get("slug") or "")
        outcomes = _parse_json_list(market.get("outcomes"))
        prices   = _parse_json_list(market.get("outcomePrices"))
        tok_ids  = _parse_json_list(market.get("clobTokenIds"))
        hours_left = _hours_until(market)

        def rej(reason: str) -> None:
            rejected.append(TrendRejected(
                strategy="trend", trend_id=tr.id,
                trend_title=tr.title, market_title=title[:80], reason=reason,
            ))

        # ── 基本檢查 ──────────────────────────────────────────────────
        if len(outcomes) != 2 or len(tok_ids) != 2:
            rej("非標準二元市場")
            continue
        if hours_left < config.TREND_MIN_HOURS_LEFT:
            rej(f"距結算 {hours_left:.0f}h < {config.TREND_MIN_HOURS_LEFT:.0f}h")
            continue

        # ── 熱度檢查 ──────────────────────────────────────────────────
        if tr.heat < config.TREND_MIN_HEAT:
            rej(f"熱度 {tr.heat:.0f} < {config.TREND_MIN_HEAT:.0f}")
            continue

        # ── 情緒偵測 ──────────────────────────────────────────────────
        side, strength = _sentiment(tr.title)
        if not side:
            rej(f"話題情緒中性，無法判斷方向（{tr.title[:40]}）")
            continue

        # ── 信心計算 ──────────────────────────────────────────────────
        conf = _confidence(tr, strength)
        if conf < config.TREND_MIN_CONFIDENCE:
            rej(f"信心 {conf:.2f} < {config.TREND_MIN_CONFIDENCE} (heat={tr.heat}, strength={strength:.2f})")
            continue

        # ── 找對應 outcome ─────────────────────────────────────────────
        outcome_index = next(
            (i for i, o in enumerate(outcomes) if str(o).upper() == side), -1
        )
        if outcome_index < 0:
            rej(f"side {side} 不在 outcomes {outcomes}")
            continue
        token_id = str(tok_ids[outcome_index])

        # ── 訂單簿 ────────────────────────────────────────────────────
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
            rej(f"進場價 {suggested_price:.3f} 不在 [{config.TREND_MIN_ENTRY_PRICE}, {config.TREND_MAX_ENTRY_PRICE}]")
            continue

        # ── 下單規模 ──────────────────────────────────────────────────
        ratio = conf            # 信心越高，比例越大（0-1）
        target_usdc = max(MIN_BET_USDC, min(config.MAX_BET_USDC, config.MAX_BET_USDC * ratio))
        suggested_size = round(target_usdc / suggested_price, 2)
        actual_cost    = round(suggested_size * suggested_price, 2)

        try:
            mid = float(prices[outcome_index])
        except Exception:
            mid = 0.0

        notes = ""
        if best_ask_size < suggested_size:
            notes = f"⚠️ ask size {best_ask_size:.0f} < 需要 {suggested_size:.0f}"

        pos_hits = [w for w in _POS if w in tr.title]
        neg_hits = [w for w in _NEG if w in tr.title]
        keywords_found = pos_hits if side == "YES" else neg_hits
        reasoning = (
            f"規則判斷 {side}：關鍵詞 {keywords_found[:3]}，"
            f"熱度 {tr.heat:.0f}，{tr.frequency} 平台，信心 {conf:.2f}"
        )

        orders.append(TrendOrder(
            strategy="trend",
            trend_id=tr.id,
            detected_at=int(time.time()),
            trend_title=tr.title,
            trend_heat=tr.heat,
            platforms=",".join(tr.platforms),
            market_title=title[:120],
            condition_id=cid,
            asset=token_id,
            outcome=str(outcomes[outcome_index]),
            outcome_index=outcome_index,
            market_price=mid,
            suggested_price=suggested_price,
            suggested_size=suggested_size,
            suggested_cost_usdc=actual_cost,
            confidence=conf,
            market_end_iso=str(market.get("endDate") or ""),
            reasoning=reasoning,
            notes=notes,
        ))
        print(f"   ✅ {side} @ {suggested_price:.3f}  信心={conf:.2f}  {title[:50]}")

    _append(_PENDING_PATH, orders)
    _append(_REJECTED_PATH, rejected)
    _save_processed(processed)
    print(f"\n  ✅ trend 通過: {len(orders)}  ❌ 拒絕: {len(rejected)}")
    return orders, rejected
