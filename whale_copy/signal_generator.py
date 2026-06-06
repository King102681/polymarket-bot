"""把 monitor 產生的 raw signal 轉成下單建議。

每個策略獨立運行，各自使用獨立的輸出檔案：
  - data/pending_orders_{strategy}.jsonl
  - data/rejected_{strategy}.jsonl
  - data/processed_{strategy}.json

使用方式：
    from whale_copy.strategies import STRATEGIES
    from whale_copy.signal_generator import process_all
    orders, rejected = process_all(STRATEGIES["political"])
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
from whale_copy.strategies import StrategyConfig

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE  = "https://clob.polymarket.com"
_TIMEOUT   = 15
_DATA_DIR  = Path(__file__).resolve().parent.parent / "data"
_SIGNALS_PATH = _DATA_DIR / "signals.jsonl"

SLIPPAGE_BUFFER = 0.005   # 0.5%
MIN_BET_USDC    = 1.0     # 單筆最低下單金額

# 黑名單：回測虧損的鯨魚 wallet（全策略共用）
WHALE_BLACKLIST: set[str] = {
    "0xbddf61af533ff524d27154e589d2d7a81510c684",  # Countryside（-$32, 47%勝率）
}


# ── 輸出路徑 ─────────────────────────────────────────────────────────────────

def _pending_path(strategy: StrategyConfig) -> Path:
    return _DATA_DIR / f"pending_orders_{strategy.name}.jsonl"

def _rejected_path(strategy: StrategyConfig) -> Path:
    return _DATA_DIR / f"rejected_{strategy.name}.jsonl"

def _processed_path(strategy: StrategyConfig) -> Path:
    return _DATA_DIR / f"processed_{strategy.name}.json"


# ── 資料類型 ──────────────────────────────────────────────────────────────────

@dataclass
class Order:
    strategy: str
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
    strategy: str
    signal_tx_hash: str
    whale_pseudonym: str
    market_title: str
    reason: str


# ── 工具函式 ──────────────────────────────────────────────────────────────────

def _load_processed(strategy: StrategyConfig) -> set[str]:
    p = _processed_path(strategy)
    if not p.exists():
        return set()
    with open(p, encoding="utf-8") as f:
        return set(json.load(f))


def _save_processed(strategy: StrategyConfig, hashes: set[str]) -> None:
    p = _processed_path(strategy)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
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
    try:
        r = requests.get(f"{CLOB_BASE}/markets/{condition_id}", timeout=_TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _fetch_market(condition_id: str) -> dict | None:
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
    size  = float(getattr(a0, "size",  None) or a0.get("size"))
    return price, size


# ── 主邏輯 ────────────────────────────────────────────────────────────────────

def process_all(strategy: StrategyConfig) -> tuple[list[Order], list[Rejected]]:
    """
    處理 signals.jsonl，依 strategy 的過濾條件輸出建議訂單。
    每個策略使用獨立的 processed hash 和輸出檔案。
    """
    print(f"\n  [{strategy.emoji} {strategy.name}] {strategy.display_name}")

    whales = discovery.load()
    if not whales:
        print("  ⚠️  whales.json 空")
        return [], []

    # whale_filter: 若策略指定 pseudonym 白名單，只跟那些
    if strategy.whale_filter:
        allowed_names = set(strategy.whale_filter)
        whales = [w for w in whales if w.pseudonym in allowed_names]
        if not whales:
            print(f"  ⚠️  whale_filter {strategy.whale_filter} 無匹配鯨魚")
            return [], []

    whale_addrs = {w.proxy_wallet for w in whales}

    signals   = _load_signals()
    processed = _load_processed(strategy)

    new_signals = [
        s for s in signals
        if s.get("transaction_hash")
        and s["transaction_hash"] not in processed
        and s["whale_wallet"] in whale_addrs
    ]
    print(f"  📥 signals: {len(signals)} 筆  已處理: {len(processed)}  待處理: {len(new_signals)}")
    if not new_signals:
        return [], []

    mkt = PolymarketClient()
    orders: list[Order]    = []
    rejected: list[Rejected] = []

    def reject(s, why: str) -> None:
        rejected.append(Rejected(
            strategy=strategy.name,
            signal_tx_hash=s["transaction_hash"],
            whale_pseudonym=s["whale_pseudonym"],
            market_title=s["market_title"],
            reason=why,
        ))

    for sig in new_signals:
        tx = sig["transaction_hash"]
        processed.add(tx)

        # 黑名單
        if sig["whale_wallet"] in WHALE_BLACKLIST:
            reject(sig, "wallet 在黑名單")
            continue

        # 鯨魚單規模
        whale_price = float(sig["whale_price"])
        whale_usdc  = whale_price * sig["whale_size"]
        if whale_usdc < strategy.min_size_usdc:
            reject(sig, f"鯨魚單 ${whale_usdc:.0f} < ${strategy.min_size_usdc:.0f}")
            continue

        # 類別過濾（在 API 呼叫前做，省流量）
        if strategy.allowed_categories:
            cat_early = classify(sig.get("market_slug"), sig.get("market_title"))
            if cat_early not in strategy.allowed_categories:
                reject(sig, f"類別 {cat_early} 不在 {strategy.allowed_categories}")
                continue

        # 查市場
        market = _fetch_market(sig["condition_id"])
        if not market:
            reject(sig, "Gamma + CLOB 均找不到此 condition_id")
            continue
        if market.get("closed") or not market.get("active"):
            reject(sig, "市場已關閉或非 active")
            continue

        hours_left = _hours_until_close(market)
        if hours_left < strategy.min_market_hours_left:
            reject(sig, f"距結算 {hours_left:.1f}h < {strategy.min_market_hours_left}h")
            continue

        # 鯨魚進場時剩餘時間過濾（避免跟當日短暫市場）
        if strategy.min_entry_hours_remaining > 0:
            hours_since = (time.time() - sig.get("detected_at", time.time())) / 3600
            entry_hours = hours_left + hours_since
            if entry_hours < strategy.min_entry_hours_remaining:
                reject(sig, f"進場時剩 {entry_hours:.0f}h < {strategy.min_entry_hours_remaining:.0f}h")
                continue

        # 訂單簿
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

        # alpha price 過濾
        suggested_price = round(min(best_ask_price * (1 + SLIPPAGE_BUFFER), 0.999), 4)
        if not (strategy.min_price <= suggested_price <= strategy.max_price):
            reject(sig, f"entry {suggested_price:.3f} 不在 [{strategy.min_price}, {strategy.max_price}]")
            continue

        # 計算下單規模
        target_usdc = whale_usdc * config.WHALE_FOLLOW_RATIO
        target_usdc = min(target_usdc, config.MAX_BET_USDC)
        if target_usdc < MIN_BET_USDC:
            reject(sig, f"建議金額 ${target_usdc:.2f} < ${MIN_BET_USDC}")
            continue
        suggested_size = round(target_usdc / suggested_price, 2)
        actual_cost    = round(suggested_size * suggested_price, 2)

        notes_parts: list[str] = []
        if best_ask_size < suggested_size:
            notes_parts.append(f"⚠️ ask size {best_ask_size:.0f} < 需要 {suggested_size:.0f}")
        if whale_usdc > config.MAX_BET_USDC * 1000:
            notes_parts.append(f"鯨魚單 ${whale_usdc:,.0f}（已 cap）")

        orders.append(Order(
            strategy=strategy.name,
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
        _append(_pending_path(strategy), orders)
    if rejected:
        _append(_rejected_path(strategy), rejected)
    _save_processed(strategy, processed)

    print(f"  ✅ 通過: {len(orders)}  ❌ 拒絕: {len(rejected)}")
    return orders, rejected
