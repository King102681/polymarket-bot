"""把 monitor 產生的 raw signal 轉成下單建議。

讀取：
  - data/signals.jsonl            raw 訊號（monitor 產出）
  - data/whales.json              認可鯨魚清單
  - data/processed_signal_hashes.json  已處理的 tx hash

輸出：
  - data/pending_orders.jsonl     通過所有檢查、可下單的建議
  - data/rejected_signals.jsonl   被拒絕的訊號 + 原因（debug 用）

不下單。下單由 executor.py 處理且預設 dry-run。
"""
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from core import config
from core.polymarket_client import PolymarketClient
from whale_copy import discovery
from whale_copy.market_classifier import classify

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
_TIMEOUT = 15
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_SIGNALS_PATH = _DATA_DIR / "signals.jsonl"
_PENDING_PATH = _DATA_DIR / "pending_orders.jsonl"
_REJECTED_PATH = _DATA_DIR / "rejected_signals.jsonl"
_PROCESSED_PATH = _DATA_DIR / "processed_signal_hashes.json"

SLIPPAGE_BUFFER = 0.005          # 0.5%
MIN_WHALE_SIZE_USDC = 500.0      # 鯨魚單規模門檻（$500：捕捉中型押注，過濾噪音）
MIN_MARKET_HOURS_LEFT = 6.0      # 距結算太近不跟
MIN_BET_USDC = 1.0               # 下單金額地板

# === 從 90 天回測學到的 alpha 過濾（Day 5 結果） ===
# 鯨魚進場價 0.20-0.80 區間 ROI +5%；其他區間虧或扣費後微虧
MIN_ENTRY_PRICE = 0.20
MAX_ENTRY_PRICE = 0.80

# 黑名單：回測虧損的鯨魚 wallet
# 0xbddf61af... (Countryside / "Unique-Congressperson") 90d 回測 -$32, 47% 勝率
WHALE_BLACKLIST: set[str] = {
    "0xbddf61af533ff524d27154e589d2d7a81510c684",
}

# 允許的市場類別（回測：other IS=+30% OOS=+27%；sports IS=-24% 捨棄）
# 設成空 set = 不限制類別
ALLOWED_CATEGORIES: set[str] = {"other"}


@dataclass
class Order:
    signal_tx_hash: str
    detected_at: int
    whale_wallet: str
    whale_pseudonym: str
    market_title: str
    market_category: str
    condition_id: str
    asset: str
    outcome: str
    outcome_index: int
    whale_price: float
    whale_size_usdc: float
    suggested_price: float
    suggested_size: float
    suggested_cost_usdc: float
    market_end_iso: str
    notes: str


@dataclass
class Rejected:
    signal_tx_hash: str
    whale_pseudonym: str
    market_title: str
    reason: str


def _load_processed() -> set[str]:
    if not _PROCESSED_PATH.exists():
        return set()
    with open(_PROCESSED_PATH, encoding="utf-8") as f:
        return set(json.load(f))


def _save_processed(hashes: set[str]) -> None:
    _PROCESSED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_PROCESSED_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(hashes), f)


def _load_signals() -> list[dict]:
    if not _SIGNALS_PATH.exists():
        return []
    return [json.loads(l) for l in open(_SIGNALS_PATH, encoding="utf-8") if l.strip()]


def _append(path: Path, items: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for x in items:
            f.write(json.dumps(asdict(x), ensure_ascii=False) + "\n")


def _fetch_market_gamma(condition_id: str) -> dict | None:
    """用 Gamma API 查詢市場（優先）。回傳 None 表示找不到。"""
    try:
        r = requests.get(
            f"{GAMMA_BASE}/markets",
            params={"condition_ids": condition_id},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and data:
            return data[0]
    except Exception:
        pass
    return None


def _fetch_market_clob(condition_id: str) -> dict | None:
    """用 CLOB API 查詢市場（fallback）。Gamma 看不到已關閉市場時使用。"""
    try:
        r = requests.get(f"{CLOB_BASE}/markets/{condition_id}", timeout=_TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _fetch_market(condition_id: str) -> dict | None:
    """先試 Gamma，找不到則 fallback 到 CLOB。"""
    data = _fetch_market_gamma(condition_id)
    if data:
        return data
    return _fetch_market_clob(condition_id)


def _hours_until_close(market: dict) -> float:
    end = market.get("endDate") or market.get("end_date_iso")
    if not end:
        return 0.0
    try:
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return (end_dt.timestamp() - time.time()) / 3600
    except Exception:
        return 0.0


def _best_ask(book) -> tuple[float, float] | None:
    asks = getattr(book, "asks", None)
    if asks is None and isinstance(book, dict):
        asks = book.get("asks")
    if not asks:
        return None
    a0 = asks[0]
    price = float(getattr(a0, "price", None) or a0.get("price"))
    size = float(getattr(a0, "size", None) or a0.get("size"))
    return price, size


def process_all() -> tuple[list[Order], list[Rejected]]:
    whales = discovery.load()
    if not whales:
        print("⚠️  whales.json 空")
        return [], []
    whale_addrs = {w.proxy_wallet for w in whales}

    signals = _load_signals()
    processed = _load_processed()
    new_signals = [
        s for s in signals
        if s.get("transaction_hash")
        and s["transaction_hash"] not in processed
        and s["whale_wallet"] in whale_addrs
    ]
    print(f"📥 載入 {len(signals)} 筆訊號，已處理 {len(processed)} 筆")
    print(f"🔍 待處理（屬於認可鯨魚 + 未處理）: {len(new_signals)} 筆")
    if not new_signals:
        return [], []

    mkt = PolymarketClient()
    orders: list[Order] = []
    rejected: list[Rejected] = []

    def reject(s, why: str) -> None:
        rejected.append(Rejected(
            signal_tx_hash=s["transaction_hash"],
            whale_pseudonym=s["whale_pseudonym"],
            market_title=s["market_title"],
            reason=why,
        ))

    for sig in new_signals:
        tx = sig["transaction_hash"]
        processed.add(tx)

        if sig["whale_wallet"] in WHALE_BLACKLIST:
            reject(sig, f"wallet 在黑名單（回測虧損）")
            continue

        # 類別過濾（在 API 呼叫之前做，省資源）
        if ALLOWED_CATEGORIES:
            cat_early = classify(sig.get("market_slug"), sig.get("market_title"))
            if cat_early not in ALLOWED_CATEGORIES:
                reject(sig, f"類別 {cat_early} 不在允許清單（只跟 {ALLOWED_CATEGORIES}）")
                continue

        whale_price = float(sig["whale_price"])
        whale_usdc = whale_price * sig["whale_size"]
        if whale_usdc < MIN_WHALE_SIZE_USDC:
            reject(sig, f"鯨魚單 ${whale_usdc:.0f} < ${MIN_WHALE_SIZE_USDC:.0f}")
            continue

        market = _fetch_market(sig["condition_id"])
        if not market:
            reject(sig, "Gamma + CLOB 均找不到此 condition_id")
            continue
        if market.get("closed") or not market.get("active"):
            reject(sig, "市場已關閉或非 active")
            continue

        hours_left = _hours_until_close(market)
        if hours_left < MIN_MARKET_HOURS_LEFT:
            reject(sig, f"距結算 {hours_left:.1f}h < {MIN_MARKET_HOURS_LEFT}h")
            continue

        try:
            book = mkt.get_orderbook(sig["asset"])
        except Exception as e:
            reject(sig, f"orderbook 失敗: {type(e).__name__}")
            continue
        ba = _best_ask(book)
        if ba is None:
            reject(sig, "訂單簿無 asks")
            continue
        best_ask_price, best_ask_size = ba

        # 用「實際會進場的價」做 alpha 過濾，不是鯨魚當時的成交價
        # 鯨魚可能已把市場推到極端，使現在進場 fees 吃光獲利
        suggested_price = round(min(best_ask_price * (1 + SLIPPAGE_BUFFER), 0.999), 4)
        if not (MIN_ENTRY_PRICE <= suggested_price <= MAX_ENTRY_PRICE):
            reject(sig, f"目前 entry {suggested_price:.3f} 不在 alpha 區間 [{MIN_ENTRY_PRICE}, {MAX_ENTRY_PRICE}]")
            continue

        target_usdc = whale_usdc * config.WHALE_FOLLOW_RATIO
        target_usdc = min(target_usdc, config.MAX_BET_USDC)
        if target_usdc < MIN_BET_USDC:
            reject(sig, f"建議金額 ${target_usdc:.2f} < ${MIN_BET_USDC}")
            continue
        suggested_size = round(target_usdc / suggested_price, 2)
        actual_cost = round(suggested_size * suggested_price, 2)

        notes_parts: list[str] = []
        if best_ask_size < suggested_size:
            notes_parts.append(
                f"⚠️ ask size {best_ask_size:.0f} < 需要 {suggested_size:.0f}"
            )
        if whale_usdc > config.MAX_BET_USDC * 1000:
            notes_parts.append(f"鯨魚單規模 ${whale_usdc:,.0f}（已被 cap）")

        orders.append(Order(
            signal_tx_hash=tx,
            detected_at=int(time.time()),
            whale_wallet=sig["whale_wallet"],
            whale_pseudonym=sig["whale_pseudonym"],
            market_title=sig["market_title"],
            market_category=classify(sig.get("market_slug"), sig.get("market_title")),
            condition_id=sig["condition_id"],
            asset=sig["asset"],
            outcome=sig["outcome"],
            outcome_index=sig["outcome_index"],
            whale_price=sig["whale_price"],
            whale_size_usdc=whale_usdc,
            suggested_price=suggested_price,
            suggested_size=suggested_size,
            suggested_cost_usdc=actual_cost,
            market_end_iso=market.get("endDate") or "",
            notes="; ".join(notes_parts),
        ))

    if orders:
        _append(_PENDING_PATH, orders)
    if rejected:
        _append(_REJECTED_PATH, rejected)
    _save_processed(processed)

    print(f"\n✅ 通過: {len(orders)} → data/pending_orders.jsonl")
    print(f"❌ 拒絕: {len(rejected)} → data/rejected_signals.jsonl")
    return orders, rejected
