"""足球專項鯨魚發現：從 leaderboard 找「足球比例高 + 活躍 + 有資金」的鯨魚。

流程：
  1. 抓 profit + volume leaderboard（30d, 各 500）
  2. 基本門檻：profit≥$3k, volume≥$15k
  3. 並行拉每個候選最近 100 筆交易，算 soccer_ratio
  4. 篩 soccer_ratio≥40% 且 soccer 大單≥3 筆
  5. 輸出候選 → data/whales_soccer.json（含可直接餵給 run_soccer_backtest 的 wallet）

執行：python -m scripts.run_soccer_discovery
"""
import sys, json, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core  # noqa  DNS patch + UTF-8
sys.stdout.reconfigure(encoding="utf-8")

from whale_copy.discovery import _fetch_lb, _fetch_trades, _fetch_value
from whale_copy.sport_classifier import sport_type, is_world_cup

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_OUT_PATH = _DATA_DIR / "whales_soccer.json"

LB_LIMIT        = 500      # API 實際上限 50，靠多 window 擴池
MIN_PROFIT_30D  = 1_500
MIN_VOLUME_30D  = 8_000
MIN_VALUE_NOW   = 1_500
MIN_SOCCER_RATIO= 0.40     # 最近 100 筆中足球 ≥ 40%
MIN_SOCCER_BIG  = 3        # 足球大單($500+) ≥ 3 筆
TRADES_SAMPLE   = 100
WORKERS         = 12
MAX_CANDIDATES  = 250      # 最多驗證前 N 名候選（控制 API 量）
SWISSTONY       = "0x204f72f35326db932158cba6adff0b9a1da95e14"


def _profile(addr: str, meta: dict) -> dict | None:
    """拉交易算足球指標；不合格回 None。"""
    try:
        trades = _fetch_trades(addr, limit=TRADES_SAMPLE)
    except Exception:
        return None
    buys = [t for t in trades if (t.get("side") or "").upper() == "BUY"]
    if not buys:
        return None

    def slug(t): return t.get("slug") or t.get("title") or ""
    def title(t): return t.get("title") or ""
    def cost(t): return float(t.get("price", 0) or 0) * float(t.get("size", 0) or 0)

    soccer = [t for t in buys if sport_type(slug(t), title(t)) == "soccer"]
    ratio = len(soccer) / len(buys)
    big = [t for t in soccer if cost(t) >= 500]
    wc = [t for t in soccer if is_world_cup(slug(t), title(t))]

    if ratio < MIN_SOCCER_RATIO or len(big) < MIN_SOCCER_BIG:
        return None

    # 活躍度 + 資金（多一次 API，只對通過初篩的查）
    try:
        value = _fetch_value(addr)
    except Exception:
        value = 0.0
    if value < MIN_VALUE_NOW:
        return None

    return {
        "pseudonym": meta["pseudonym"],
        "proxy_wallet": addr,
        "profit_30d": round(meta["profit_30d"], 0),
        "volume_30d": round(meta["volume_30d"], 0),
        "roi_30d": round(meta["roi_30d"], 4),
        "value_now": round(value, 0),
        "soccer_ratio": round(ratio, 3),
        "soccer_in_sample": len(soccer),
        "soccer_big": len(big),
        "soccer_big_usdc": round(sum(cost(t) for t in big), 0),
        "world_cup_in_sample": len(wc),
    }


def main():
    # leaderboard API 每批上限 50 筆，limit 參數無效 → 跨多個 window 抓取去重擴池
    windows = ["1d", "7d", "30d", "all"]
    print(f"📡 抓 leaderboard（windows={windows}，各批 50）...")
    wallets: dict[str, dict] = {}
    for win in windows:
        for kind in ("profit", "volume"):
            try:
                lb = _fetch_lb(kind, win, limit=LB_LIMIT)
            except Exception as e:
                print(f"   ⚠️ {kind}/{win} 失敗: {type(e).__name__}")
                continue
            for e in lb:
                a = e.get("proxyWallet")
                if not a:
                    continue
                amt = float(e.get("amount") or 0)
                w = wallets.setdefault(a, {
                    "pseudonym": e.get("pseudonym") or e.get("name") or "?",
                    "profit_30d": 0.0, "volume_30d": 0.0,
                })
                # 用 30d 當主指標；其他 window 僅擴充候選池
                if win == "30d" and kind == "profit":
                    w["profit_30d"] = amt
                elif win == "30d" and kind == "volume":
                    w["volume_30d"] = amt
                # 確保非 30d 進池的也有粗略 profit/volume 估計
                if kind == "profit" and w["profit_30d"] == 0:
                    w["profit_30d"] = amt
                if kind == "volume" and w["volume_30d"] == 0:
                    w["volume_30d"] = amt
    print(f"   去重後候選池: {len(wallets)} 個錢包")

    cands = []
    for a, d in wallets.items():
        if d["profit_30d"] < MIN_PROFIT_30D or d["volume_30d"] < MIN_VOLUME_30D:
            continue
        d["roi_30d"] = d["profit_30d"] / d["volume_30d"] if d["volume_30d"] else 0
        cands.append((d["roi_30d"], a, d))
    cands.sort(key=lambda x: -x[0])
    cands = cands[:MAX_CANDIDATES]
    print(f"   基本門檻後 {len(cands)} 候選，並行驗證足球比例（{WORKERS} workers）...")

    found = []
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(_profile, a, d): (a, d) for _, a, d in cands}
        for fut in as_completed(futs):
            done += 1
            r = fut.result()
            if r:
                found.append(r)
                flag = "🆕" if r["proxy_wallet"] != SWISSTONY else "⭐"
                print(f"   {flag} {r['pseudonym'][:24]:24s}  soccer={r['soccer_ratio']:.0%}  "
                      f"big={r['soccer_big']:2d}(${r['soccer_big_usdc']:,.0f})  "
                      f"WC={r['world_cup_in_sample']:2d}  roi={r['roi_30d']:.1%}  val=${r['value_now']:,.0f}")
            if done % 50 == 0:
                print(f"   ...{done}/{len(cands)} 驗證完成（已找到 {len(found)}）")

    found.sort(key=lambda x: -x["soccer_big_usdc"])
    _OUT_PATH.write_text(json.dumps(found, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{'='*68}")
    print(f"  ⚽ 找到 {len(found)} 隻足球鯨魚（按足球大單金額排序）")
    print(f"{'='*68}")
    for r in found[:12]:
        mark = " ⭐swisstony" if r["proxy_wallet"] == SWISSTONY else ""
        print(f"  {r['pseudonym'][:22]:22s}  soccer={r['soccer_ratio']:>4.0%}  "
              f"big={r['soccer_big']:>2d}  ${r['soccer_big_usdc']:>9,.0f}  "
              f"WC={r['world_cup_in_sample']:>2d}{mark}")

    # 印出可直接餵給回測的 wallet（排除 swisstony）
    others = [r["proxy_wallet"] for r in found if r["proxy_wallet"] != SWISSTONY][:3]
    if others:
        print(f"\n▶ 下一步深度回測 top 3：")
        print(f"   python -m scripts.run_soccer_backtest {' '.join(others)}")
    print(f"\n✅ 已存 → {_OUT_PATH}")


if __name__ == "__main__":
    main()
