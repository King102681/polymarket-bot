"""sports_live 策略價格區間回測：swisstony 的大單($500+)在不同進場價區間的 edge 如何分布。

目的：判斷目前 price 區間 [0.70, 0.97] 是否切在正確的位置——
是否該往下鬆綁（捕捉更多訊號）或往上/下收緊（避開負 edge 區）。

核心指標同 run_soccer_backtest.py：edge = 實際勝率 − 平均進場價。
這裡不分運動類別（sports_live 沒有 sport_filter），只依進場價分桶。

執行：python -m scripts.run_sports_live_backtest
"""
import sys, json, time, statistics
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core  # noqa  DNS patch + UTF-8
sys.stdout.reconfigure(encoding="utf-8")

from backtest.pull_historical import fetch_all_trades, fetch_markets_for_conditions, coverage_shortfall
from backtest.fees import DEFAULT_SLIPPAGE_RATIO as TAKER_FEE

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_BT_DIR   = _DATA_DIR / "backtest"
_OUT_PATH = _BT_DIR / "sports_live_backtest.json"

LOOKBACK_DAYS = 90
MIN_BET_USDC  = 500.0   # 對齊 strategies.py 的 sports_live min_size_usdc
FOLLOW_RATIO  = 0.001
MAX_BET_USDC  = 10.0
FOLLOW_MIN    = 1.0

SWISSTONY = ("swisstony", "0x204f72f35326db932158cba6adff0b9a1da95e14")

# 目前策略區間 + 候選擴增區間（兩端各探一段）
BANDS = [
    (0.00, 0.50), (0.50, 0.60), (0.60, 0.70),
    (0.70, 0.80), (0.80, 0.90), (0.90, 0.97),   # 目前啟用區間集中在這三段
    (0.97, 0.99), (0.99, 1.00),
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


def main():
    _BT_DIR.mkdir(parents=True, exist_ok=True)
    name, wallet = SWISSTONY
    since = int(time.time()) - LOOKBACK_DAYS * 86400

    print(f"📡 拉 {name} 過去 {LOOKBACK_DAYS} 天 trades...")
    trades = fetch_all_trades(wallet, since)
    buys = [t for t in trades if (t.get("side") or "").upper() == "BUY"]
    print(f"   {len(trades)} 筆全部 / {len(buys)} 筆 BUY")
    shortfall = coverage_shortfall()
    if shortfall:
        print(f"   ⚠️⚠️⚠️ 資料覆蓋不足：只拉到 {shortfall['short_days']:.1f} 天前（要求 {LOOKBACK_DAYS} 天），"
              f"鯨魚當前交易量過大（可能單日爆量事件，例如賽事期間）。")
        print(f"   ⚠️⚠️⚠️ 以下結果不能代表真正 {LOOKBACK_DAYS} 天的歷史分布，僅反映近期這一小段時間，不建議用來做策略參數決策。")

    def cost(t):
        return float(t.get("price", 0) or 0) * float(t.get("size", 0) or 0)

    big = [t for t in buys if cost(t) >= MIN_BET_USDC]
    print(f"   大單($500+): {len(big)} 筆")

    cids = sorted({t.get("conditionId") for t in big if t.get("conditionId")})
    print(f"📡 查 {len(cids)} 個市場結算...")
    markets = fetch_markets_for_conditions(cids)
    closed = sum(1 for m in markets.values() if m.get("closed"))
    print(f"   {len(markets)} 個（已結算 {closed}）")

    rows = []
    for t in big:
        cid = t.get("conditionId", "")
        m = markets.get(cid)
        if not m:
            continue
        w = _won(t, m)
        if w is None:
            continue
        price = float(t.get("price", 0) or 0)
        rows.append((price, w, cost(t)))

    print(f"\n已結算大單樣本：{len(rows)} 筆\n")
    print(f"{'='*78}")
    print(f"  🎾 swisstony 大單($500+) 依進場價分桶 — edge = 勝率 − 進場價")
    print(f"{'='*78}")
    print(f"  {'區間':>12s}  {'n':>5s}  {'勝率':>7s}  {'均進場價':>9s}  {'edge':>8s}  "
          f"{'跟單ROI':>9s}  {'目前啟用?':>8s}")

    report_bands = []
    for lo, hi in BANDS:
        subset = [(p, w, c) for p, w, c in rows if lo <= p < hi]
        active = "✅" if (lo >= 0.70 - 1e-9 and hi <= 0.97 + 1e-9) else "—"
        if not subset:
            print(f"  [{lo:.2f},{hi:.2f})  {0:>5d}  {'—':>7s}  {'—':>9s}  {'—':>8s}  {'—':>9s}  {active:>8s}")
            report_bands.append({"range": [lo, hi], "n": 0})
            continue
        n = len(subset)
        win_rate = sum(1 for _, w, _ in subset if w) / n
        avg_entry = statistics.mean(p for p, _, _ in subset)
        edge = win_rate - avg_entry

        # 跟單模擬（同 soccer 回測的縮小邏輯）
        pnl = fcost = 0.0
        for p, w, c in subset:
            if p <= 0:
                continue
            fc = min(c * FOLLOW_RATIO, MAX_BET_USDC)
            if fc < FOLLOW_MIN:
                continue
            shares = fc / p
            fee = fc * TAKER_FEE
            pnl += (shares - fc - fee) if w else (-fc - fee)
            fcost += fc
        roi = pnl / fcost if fcost else None

        print(f"  [{lo:.2f},{hi:.2f})  {n:>5d}  {win_rate:>6.1%}  {avg_entry:>8.1%}  "
              f"{edge:>+7.1%}  {(f'{roi:+.1%}' if roi is not None else '—'):>9s}  {active:>8s}")
        report_bands.append({
            "range": [lo, hi], "n": n, "win_rate": round(win_rate, 4),
            "avg_entry": round(avg_entry, 4), "edge": round(edge, 4),
            "follow_roi": round(roi, 4) if roi is not None else None,
        })

    # 全樣本整體 + 目前啟用區間整體（方便對照）
    def block(subset):
        if not subset:
            return {"n": 0}
        n = len(subset)
        win_rate = sum(1 for _, w, _ in subset if w) / n
        avg_entry = statistics.mean(p for p, _, _ in subset)
        return {"n": n, "win_rate": round(win_rate, 4), "avg_entry": round(avg_entry, 4),
                "edge": round(win_rate - avg_entry, 4)}

    all_block = block(rows)
    active_block = block([(p, w, c) for p, w, c in rows if 0.70 <= p < 0.97])
    below_block = block([(p, w, c) for p, w, c in rows if p < 0.70])
    above_block = block([(p, w, c) for p, w, c in rows if p >= 0.97])

    print(f"\n  全樣本           n={all_block.get('n',0):>4d}  edge={all_block.get('edge',0):>+.1%}")
    print(f"  目前啟用[0.70,0.97) n={active_block.get('n',0):>4d}  edge={active_block.get('edge',0):>+.1%}")
    print(f"  <0.70（鬆綁候選）  n={below_block.get('n',0):>4d}  edge={below_block.get('edge',0):>+.1%}")
    print(f"  >=0.97（目前排除） n={above_block.get('n',0):>4d}  edge={above_block.get('edge',0):>+.1%}")

    _OUT_PATH.write_text(json.dumps({
        "generated_at": int(time.time()),
        "lookback_days": LOOKBACK_DAYS,
        "bands": report_bands,
        "all": all_block,
        "active_0.70_0.97": active_block,
        "below_0.70": below_block,
        "above_0.97": above_block,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✅ 報告已存 → {_OUT_PATH}")


if __name__ == "__main__":
    main()
