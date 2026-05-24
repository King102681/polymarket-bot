"""逐筆模擬：對歷史 BUY trade，假設跟單 $X，計算 PnL。

跟單規則與 signal_generator 對齊（金額計算、過濾門檻），讓回測結果可預測實盤。
"""
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from core import config
from backtest.fees import entry_price_with_slippage, estimate_trade_cost
from whale_copy.market_classifier import classify

_BACKTEST_DIR = Path(__file__).resolve().parent.parent / "data" / "backtest"
_MARKETS_PATH = _BACKTEST_DIR / "markets_resolved.json"
_RESULTS_PATH = _BACKTEST_DIR / "simulation_results.jsonl"

MIN_WHALE_SIZE_USDC = 2000.0
MIN_BET_USDC = 1.0


@dataclass
class SimResult:
    whale_pseudonym: str
    trade_ts: int
    days_ago: float
    market_title: str
    market_category: str
    condition_id: str
    outcome: str
    outcome_index: int
    whale_price: float
    whale_size_usdc: float
    passed_filter: bool
    rejection_reason: str
    bet_usdc: float
    entry_price: float
    shares: float
    market_resolved: bool
    winning_outcome_index: int  # -1 if not resolved
    payout: float
    fees: float
    net_pnl: float


def _load_trades(path: Path) -> list[dict]:
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def _load_markets() -> dict[str, dict]:
    if not _MARKETS_PATH.exists():
        return {}
    return json.load(open(_MARKETS_PATH, encoding="utf-8"))


def _winning_outcome(market: dict) -> str | None:
    """從 CLOB market 找贏家的 outcome 字串（如 "Yes" / "Michigan Wolverines"）"""
    for tk in market.get("tokens", []) or []:
        if tk.get("winner") is True or float(tk.get("price") or 0) >= 0.99:
            return tk.get("outcome")
    return None


def simulate_one(trade: dict, market: Optional[dict], now_ts: int) -> SimResult:
    whale_price = float(trade.get("price") or 0)
    whale_size = float(trade.get("size") or 0)
    whale_usdc = whale_price * whale_size
    market_resolved = bool(market and market.get("closed"))
    winning_outcome = _winning_outcome(market) if market_resolved else None
    winning_idx = -1
    if market_resolved and market and market.get("tokens"):
        for i, tk in enumerate(market["tokens"]):
            if tk.get("outcome") == winning_outcome:
                winning_idx = i
                break

    r = SimResult(
        whale_pseudonym=trade.get("pseudonym") or trade.get("name", "?"),
        trade_ts=int(trade.get("timestamp", 0)),
        days_ago=(now_ts - int(trade.get("timestamp", 0))) / 86400.0,
        market_title=trade.get("title", ""),
        market_category=classify(trade.get("slug"), trade.get("title")),
        condition_id=trade.get("conditionId", ""),
        outcome=trade.get("outcome", ""),
        outcome_index=int(trade.get("outcomeIndex") or 0),
        whale_price=whale_price,
        whale_size_usdc=whale_usdc,
        passed_filter=False,
        rejection_reason="",
        bet_usdc=0.0,
        entry_price=0.0,
        shares=0.0,
        market_resolved=market_resolved,
        winning_outcome_index=winning_idx,
        payout=0.0,
        fees=0.0,
        net_pnl=0.0,
    )

    if whale_usdc < MIN_WHALE_SIZE_USDC:
        r.rejection_reason = f"whale_usdc {whale_usdc:.0f} < {MIN_WHALE_SIZE_USDC:.0f}"
        return r
    if not market:
        r.rejection_reason = "market_missing"
        return r

    target = min(whale_usdc * config.WHALE_FOLLOW_RATIO, config.MAX_BET_USDC)
    if target < MIN_BET_USDC:
        r.rejection_reason = f"bet ${target:.2f} < ${MIN_BET_USDC}"
        return r

    entry = entry_price_with_slippage(whale_price)
    shares = target / entry
    fees = estimate_trade_cost(target)

    r.passed_filter = True
    r.bet_usdc = round(target, 2)
    r.entry_price = round(entry, 4)
    r.shares = round(shares, 4)
    r.fees = round(fees, 4)

    if market_resolved:
        # 用 outcome 字串比對：鯨魚買的 outcome 是否等於 winner
        if winning_outcome is not None and winning_outcome == r.outcome:
            r.payout = round(shares * 1.0, 4)
        else:
            r.payout = 0.0
        r.net_pnl = round(r.payout - target - fees, 4)
    # 未結算：payout 與 net_pnl 留 0，由 analyzer 排除

    return r


def simulate_all() -> list[SimResult]:
    markets = _load_markets()
    print(f"📊 載入 {len(markets)} 個市場資料")

    now_ts = int(time.time())
    results: list[SimResult] = []

    for tf in sorted(_BACKTEST_DIR.glob("trades_*.jsonl")):
        trades = _load_trades(tf)
        print(f"   {tf.name}: {len(trades)} 筆 BUY")
        for t in trades:
            cid = t.get("conditionId", "")
            results.append(simulate_one(t, markets.get(cid), now_ts))

    with open(_RESULTS_PATH, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
    print(f"💾 已存 {_RESULTS_PATH.name}（{len(results)} 筆）")
    return results
