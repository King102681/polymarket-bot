"""swisstony 90 天回測：驗證在 0.20-0.87 價格區間跟單是否有 alpha。

步驟：
  1. 拉 swisstony 過去 90 天 BUY trades（Data API）
  2. 查各市場結算狀態（CLOB API）
  3. 模擬跟單（含手續費），計算 IS/OOS PnL
  4. 按進場價區間分析（0.20-0.80 vs 0.80-0.87 vs >0.87）

執行：
    python -m scripts.run_swisstony_backtest   （需接熱點）

數據來源說明：
  - 交易紀錄：data-api.polymarket.com/trades?user={wallet}
  - 市場結算：clob.polymarket.com/markets/{condition_id}
  - 鯨魚排行：lb-api.polymarket.com/profit?window=30d
"""
import sys, json, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core  # noqa  DNS patch + UTF-8

import requests
from backtest.pull_historical import fetch_all_trades, fetch_markets_for_conditions
from whale_copy.market_classifier import classify
from backtest.fees import TAKER_FEE_RATE

_DATA_DIR  = Path(__file__).resolve().parent.parent / "data"
_BT_DIR    = _DATA_DIR / "backtest"
_OUT_PATH  = _BT_DIR / "swisstony_backtest.json"

SWISSTONY_WALLET = "0x204f72f35326db932158cba6adff0b9a1da95e14"
LOOKBACK_DAYS    = 90
IS_DAYS          = 30    # OOS = 最近 30 天；IS = 30-90 天前
FOLLOW_RATIO     = 0.001
MAX_BET_USDC     = 10.0
MIN_BET_USDC     = 1.0
TAKER_FEE        = TAKER_FEE_RATE  # 0.20%


def simulate_trade(trade: dict, market: dict) -> dict | None:
    """
    模擬跟單一筆 trade，回傳 {pnl, cost, won, ...} 或 None（跳過）。
    """
    price     = float(trade.get("price", 0) or 0)
    size      = float(trade.get("size", 0) or 0)
    whale_cost = price * size

    if whale_cost < 500:          # 鯨魚單太小
        return None
    if not (0.20 <= price <= 0.87):  # 進場價不在區間
        return None
    if market.get("closed") is False:  # 未結算，跳過
        return None

    # 判斷是否 WIN：找到 tokens 中 winner = True 的那個 tokenId
    tokens = market.get("tokens") or []
    outcome_token = trade.get("outcomeIndex")  # 0=YES or 1=NO typically
    asset = trade.get("asset") or trade.get("tokenId") or trade.get("outcomeId") or ""

    won = False
    for tok in tokens:
        if tok.get("tokenId") == asset and tok.get("winner") is True:
            won = True
            break

    # 跟單金額
    follow_cost = min(whale_cost * FOLLOW_RATIO, MAX_BET_USDC)
    if follow_cost < MIN_BET_USDC:
        return None

    follow_shares = follow_cost / price
    fee = follow_cost * TAKER_FEE

    if won:
        pnl = follow_shares - follow_cost - fee   # 收到 1/share，扣回本 扣手續費
    else:
        pnl = -follow_cost - fee

    return {
        "pnl": round(pnl, 4),
        "cost": round(follow_cost, 4),
        "won": won,
        "price": price,
        "whale_cost": round(whale_cost, 2),
        "category": classify(trade.get("slug") or trade.get("market_slug"),
                             trade.get("title") or trade.get("market_title")),
        "market_title": (trade.get("title") or trade.get("market_title") or "")[:60],
        "ts": int(trade.get("timestamp", 0)),
    }


def main():
    _BT_DIR.mkdir(parents=True, exist_ok=True)
    now_ts     = int(time.time())
    since_ts   = now_ts - LOOKBACK_DAYS * 86400
    oos_cutoff = now_ts - IS_DAYS * 86400   # 比這新的是 OOS

    print(f"📡 拉 swisstony 過去 {LOOKBACK_DAYS} 天交易...")
    trades = fetch_all_trades(SWISSTONY_WALLET, since_ts)
    buys = [t for t in trades if (t.get("side") or "").upper() == "BUY"]
    print(f"   全部 {len(trades)} 筆，BUY {len(buys)} 筆")

    cids = list({t["conditionId"] for t in buys if t.get("conditionId")})
    print(f"📡 查 {len(cids)} 個市場結算狀態...")
    markets = fetch_markets_for_conditions(cids)

    # 存市場快取（可合併進全域快取）
    markets_path = _BT_DIR / "markets_swisstony.json"
    markets_path.write_text(json.dumps(markets, indent=2, ensure_ascii=False), encoding="utf-8")

    # 模擬
    results, skipped = [], 0
    for t in buys:
        cid = t.get("conditionId", "")
        m = markets.get(cid)
        if not m:
            skipped += 1
            continue
        r = simulate_trade(t, m)
        if r is None:
            skipped += 1
            continue
        r["is_oos"] = t.get("timestamp", 0) >= oos_cutoff
        results.append(r)

    print(f"\n   模擬 {len(results)} 筆（跳過 {skipped} 筆）")

    # ── 分析 ──────────────────────────────────────────────────────
    def stats(subset):
        if not subset: return {"n":0,"pnl":0,"cost":0,"roi":0,"win_rate":0}
        pnl  = sum(r["pnl"] for r in subset)
        cost = sum(r["cost"] for r in subset)
        wins = sum(1 for r in subset if r["won"])
        return {
            "n": len(subset),
            "pnl": round(pnl, 4),
            "cost": round(cost, 4),
            "roi": round(pnl / cost, 4) if cost else 0,
            "win_rate": round(wins / len(subset), 3),
        }

    is_all  = [r for r in results if not r["is_oos"]]
    oos_all = [r for r in results if r["is_oos"]]

    # 按進場價區間
    buckets = {
        "0.20-0.80": lambda r: 0.20 <= r["price"] <= 0.80,
        "0.80-0.87": lambda r: 0.80 <  r["price"] <= 0.87,
        "0.20-0.87": lambda r: 0.20 <= r["price"] <= 0.87,
    }

    print(f"\n{'='*65}")
    print(f" swisstony 回測（$500+ 鯨魚單，跟單比 {FOLLOW_RATIO}，上限 ${MAX_BET_USDC}）")
    print(f"{'='*65}")
    print(f" IS = {LOOKBACK_DAYS-IS_DAYS}-{LOOKBACK_DAYS} 天前   OOS = 最近 {IS_DAYS} 天")
    print(f"{'='*65}")

    report = {}
    for label, fn in buckets.items():
        is_s  = stats([r for r in is_all  if fn(r)])
        oos_s = stats([r for r in oos_all if fn(r)])
        report[label] = {"IS": is_s, "OOS": oos_s}
        print(f"\n 進場價 {label}:")
        print(f"   IS  n={is_s['n']:3d}  pnl=${is_s['pnl']:+.2f}  cost=${is_s['cost']:.2f}  "
              f"ROI={is_s['roi']:+.1%}  win={is_s['win_rate']:.0%}")
        print(f"   OOS n={oos_s['n']:3d}  pnl=${oos_s['pnl']:+.2f}  cost=${oos_s['cost']:.2f}  "
              f"ROI={oos_s['roi']:+.1%}  win={oos_s['win_rate']:.0%}")

    # 按類別
    print(f"\n{'─'*65}")
    print(" 各類別（全部 0.20-0.87）：")
    all_trades = [r for r in results if 0.20 <= r["price"] <= 0.87]
    cats = sorted({r["category"] for r in all_trades})
    for cat in cats:
        sub = [r for r in all_trades if r["category"] == cat]
        s = stats(sub)
        print(f"   {cat:10s}  n={s['n']:3d}  pnl=${s['pnl']:+.2f}  ROI={s['roi']:+.1%}  win={s['win_rate']:.0%}")

    # 存報告
    _OUT_PATH.write_text(json.dumps({
        "generated_at": now_ts,
        "wallet": SWISSTONY_WALLET,
        "lookback_days": LOOKBACK_DAYS,
        "total_trades": len(buys),
        "simulated": len(results),
        "by_price_bucket": report,
    }, indent=2), encoding="utf-8")
    print(f"\n✅ 報告已存 → {_OUT_PATH}")


if __name__ == "__main__":
    main()
