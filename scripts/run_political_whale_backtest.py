"""political 策略鯨魚候選驗證：other 類別 edge 是否為正。

同 run_soccer_backtest.py 的邏輯，但鎖定 other 類別（政治/地緣/總經）——
這是 political 策略 whale_filter 真正要跟的市場類型，呼應 The Spirit of
Ukraine>UMA（sports_ratio=0%）的畫像。高利潤/高 ROI 不代表 other 類別有
alpha，必須跟 soccer 鯨魚一樣分類別驗證（見 CLAUDE.md「已評估未採用：
GoalLineGhost」的教訓）才能決定是否加入 whale_filter。

核心指標同 run_soccer_backtest.py：edge = 實際勝率 − 平均進場價。

執行：python -m scripts.run_political_whale_backtest <pseudonym1>:<wallet1> [<pseudonym2>:<wallet2> ...]
      不帶參數則預設驗證本輪 smart discovery 找到的兩個候選（Q96s3kwozynxpau, maz26）。
"""
import sys, time, statistics
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core  # noqa  DNS patch + UTF-8
sys.stdout.reconfigure(encoding="utf-8")

from backtest.pull_historical import fetch_all_trades, fetch_markets_for_conditions, coverage_shortfall
from backtest.fees import DEFAULT_SLIPPAGE_RATIO as TAKER_FEE
from whale_copy.market_classifier import classify

LOOKBACK_DAYS = 90
FOLLOW_RATIO  = 0.001
MAX_BET_USDC  = 10.0
MIN_BET_USDC  = 1.0
BIG_BET_USDC  = 100.0   # 對齊 strategies.py political 的 min_size_usdc

# 2026-07-10 smart discovery 找到的候選（sports_ratio 極低，呼應 Spirit of Ukraine 畫像）
DEFAULT_TARGETS = [
    ("Q96s3kwozynxpau", "0x2663daca3cecf3767ca1c3b126002a8578a8ed1f"),  # sports=0%, other=100%
    ("maz26", "0x67542c3219b37fd1610aad290676ff91cdbfe3bc"),           # sports=41%, other=59%
]


def _winning_outcome(market: dict) -> str | None:
    for tk in (market.get("tokens") or []):
        if tk.get("winner") is True or float(tk.get("price") or 0) >= 0.99:
            return tk.get("outcome")
    return None


def _won(trade: dict, market: dict) -> bool | None:
    if not market.get("closed"):
        return None
    win_out = _winning_outcome(market)
    if not win_out:
        return None
    t_out = (trade.get("outcome") or trade.get("outcomeName") or "")
    if not t_out:
        return None
    return t_out.strip().lower() == win_out.strip().lower()


def _slug(t: dict) -> str:
    return t.get("slug") or t.get("market_slug") or t.get("eventSlug") or ""


def _title(t: dict) -> str:
    return t.get("title") or t.get("market_title") or ""


def analyze(pseudonym: str, trades: list[dict], markets: dict[str, dict]) -> dict:
    buys = [t for t in trades if (t.get("side") or "").upper() == "BUY"]
    other = [t for t in buys if classify(_slug(t), _title(t)) == "other"]

    def cost(t):
        return float(t.get("price", 0) or 0) * float(t.get("size", 0) or 0)

    def edge_block(subset: list[dict]) -> dict:
        rows = []
        for t in subset:
            cid = t.get("conditionId", "")
            m = markets.get(cid)
            if not m:
                continue
            w = _won(t, m)
            if w is None:
                continue
            rows.append((float(t.get("price", 0) or 0), w, cost(t)))
        if not rows:
            return {"n": 0}
        win_rate = sum(1 for _, w, _ in rows if w) / len(rows)
        avg_entry = statistics.mean(p for p, _, _ in rows)
        return {"n": len(rows), "win_rate": round(win_rate, 4),
                "avg_entry_price": round(avg_entry, 4), "edge": round(win_rate - avg_entry, 4)}

    big = [t for t in other if cost(t) >= BIG_BET_USDC]

    # 跟單模擬（只跟達 political min_size 門檻的單）
    pnl = fcost = wins = n = 0.0
    for t in big:
        cid = t.get("conditionId", "")
        m = markets.get(cid)
        if not m:
            continue
        w = _won(t, m)
        if w is None:
            continue
        price = float(t.get("price", 0) or 0)
        if price <= 0:
            continue
        fc = min(cost(t) * FOLLOW_RATIO, MAX_BET_USDC)
        if fc < MIN_BET_USDC:
            continue
        shares = fc / price
        fee = fc * TAKER_FEE
        pnl += (shares - fc - fee) if w else (-fc - fee)
        fcost += fc
        n += 1
        wins += 1 if w else 0

    return {
        "pseudonym": pseudonym,
        "other_buys": len(other),
        "other_ratio": round(len(other) / len(buys), 3) if buys else 0,
        "big_bets_100plus": len(big),
        "edge_all_other": edge_block(other),
        "edge_big_other": edge_block(big),
        "follow": {
            "n": int(n), "wins": int(wins),
            "win_rate": round(wins / n, 3) if n else 0,
            "pnl": round(pnl, 2), "cost": round(fcost, 2),
            "roi": round(pnl / fcost, 4) if fcost else None,
        },
    }


def _print_report(r: dict) -> None:
    print(f"\n{'='*68}")
    print(f"  🏛️  {r['pseudonym']}  political 鯨魚候選驗證（other 類別, 過去 {LOOKBACK_DAYS} 天）")
    print(f"{'='*68}")
    print(f"  other 類別 BUY 筆數: {r['other_buys']:>6d}   佔全部 BUY 比例: {r['other_ratio']:.0%}")
    print(f"  ≥$100 大單筆數:      {r['big_bets_100plus']:>6d}")

    ea, eb = r["edge_all_other"], r["edge_big_other"]
    print(f"\n  🎯 EDGE（實際勝率 − 進場價；>0 才有跟單價值，呼應 Spirit of Ukraine 的驗證邏輯）")
    if ea.get("n"):
        print(f"     全部other(n={ea['n']:>4d})   勝率={ea['win_rate']:>5.1%}  進場價={ea['avg_entry_price']:>5.1%}  edge={ea['edge']:>+6.1%}")
    else:
        print(f"     全部other：無已結算樣本")
    if eb.get("n"):
        print(f"     大單other(n={eb['n']:>4d})   勝率={eb['win_rate']:>5.1%}  進場價={eb['avg_entry_price']:>5.1%}  edge={eb['edge']:>+6.1%}")
    else:
        print(f"     大單other：無已結算樣本（樣本太少，無法判斷）")

    f = r["follow"]
    roi_str = f"{f['roi']:+.1%}" if f['roi'] is not None else "—"
    print(f"\n  💰 跟單模擬（只跟≥$100單, ×{FOLLOW_RATIO}, cap ${MAX_BET_USDC:.0f}）")
    print(f"     n={f['n']}  勝率={f['win_rate']:.1%}  PnL=${f['pnl']:+.2f}  成本=${f['cost']:.2f}  ROI={roi_str}")

    # ⚠️ 2026-07-11 修正：原本只看 edge>0 就建議加入，但 UpTheBlues 案例顯示
    # edge+1.4~1.6%（正）卻 follow ROI -8.7%（負）——手續費+滑價把薄邊際吃光。
    # edge 是「鯨魚選股能力」的訊號，follow ROI 才是「我們實際會不會賺錢」，
    # 必須以 follow ROI 為準，不能只看 edge 正負就下結論。
    roi = f.get('roi')
    if eb.get('n', 0) < 5:
        verdict = "⚠️ 樣本不足，暫緩加入"
    elif roi is None or f.get('n', 0) < 5:
        verdict = "⚠️ 跟單模擬樣本不足，暫緩加入"
    elif roi > 0:
        verdict = "✅ 建議加入 whale_filter"
    else:
        verdict = f"❌ edge 雖為 {eb.get('edge',0):+.1%} 但跟單 ROI 為負（手續費吃掉薄邊際），不建議加入"
    print(f"\n  結論：{verdict}")


def main():
    args = sys.argv[1:]
    if args:
        targets = []
        for a in args:
            name, _, wallet = a.partition(":")
            targets.append((name or wallet[:8], wallet))
    else:
        targets = DEFAULT_TARGETS

    since = int(time.time()) - LOOKBACK_DAYS * 86400
    all_cids: set[str] = set()
    trades_by_whale: dict[str, list] = {}

    for name, wallet in targets:
        print(f"📡 拉 {name} 過去 {LOOKBACK_DAYS} 天 trades...")
        trades = fetch_all_trades(wallet, since)
        shortfall = coverage_shortfall()
        if shortfall:
            print(f"   ⚠️ 資料覆蓋不足：只拉到 {shortfall['short_days']:.1f} 天前，結果可能不完整")
        trades_by_whale[name] = trades
        buys = [t for t in trades if (t.get("side") or "").upper() == "BUY"]
        other_cids = {t.get("conditionId") for t in buys if classify(_slug(t), _title(t)) == "other" and t.get("conditionId")}
        all_cids |= other_cids
        print(f"   {len(trades)} 筆全部，other 類別 condition {len(other_cids)} 個")

    print(f"\n📡 查 {len(all_cids)} 個 other 類別市場結算...")
    markets = fetch_markets_for_conditions(list(all_cids))
    closed = sum(1 for m in markets.values() if m.get("closed"))
    print(f"   {len(markets)} 個（已結算 {closed}）")

    for name, wallet in targets:
        r = analyze(name, trades_by_whale[name], markets)
        _print_report(r)


if __name__ == "__main__":
    main()
