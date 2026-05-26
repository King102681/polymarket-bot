"""擴大鯨魚池：放寬篩選門檻，目標找到 10-15 隻鯨魚。

放寬策略（對比原版 discover() 預設值）：
  - min_profit_30d : $10,000 → $5,000   （納入中型贏家）
  - min_volume_30d : $50,000 → $20,000  （納入較低流動性交易者）
  - min_value_now  : $10,000 → $5,000   （納入資金較小的鯨魚）
  - max_sports_ratio: 0.50   → 0.70     （容許體育佔比更高，但不超過 70%）
  - max_whales     : 20      → 30       （預留更多名額）

輸出：data/whales_expanded.json（不覆蓋 data/whales.json）

⚠️ 需要網路連線（mobile hotspot 或 VPN，ISP 會 block *.polymarket.com）
"""
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core  # noqa: F401  (安裝 DNS patch)

from whale_copy.discovery import Whale, _fetch_lb, _fetch_trades, _fetch_value, _TIMEOUT
from whale_copy.market_classifier import classify

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_OUT_PATH = _DATA_DIR / "whales_expanded.json"
_ORIG_PATH = _DATA_DIR / "whales.json"

# 放寬後的門檻
MIN_PROFIT_30D = 5_000
MIN_VOLUME_30D = 20_000
MIN_VALUE_NOW = 5_000
MAX_SPORTS_RATIO = 0.70
MAX_WHALES = 30
MIN_TRADES_7D = 1


def discover_expanded() -> list[Whale]:
    print(f"📡 抓 leaderboard（window=30d, 各 200 筆）")
    profit_lb = _fetch_lb("profit", "30d", limit=200)
    volume_lb = _fetch_lb("volume", "30d", limit=200)
    print(f"   profit: {len(profit_lb)}    volume: {len(volume_lb)}")

    wallets: dict[str, dict] = {}
    for e in profit_lb:
        addr = e["proxyWallet"]
        wallets[addr] = {
            "pseudonym": e.get("pseudonym") or e.get("name") or "?",
            "profit_30d": float(e.get("amount") or 0),
            "volume_30d": 0.0,
        }
    for e in volume_lb:
        addr = e["proxyWallet"]
        if addr in wallets:
            wallets[addr]["volume_30d"] = float(e.get("amount") or 0)
        else:
            wallets[addr] = {
                "pseudonym": e.get("pseudonym") or e.get("name") or "?",
                "profit_30d": 0.0,
                "volume_30d": float(e.get("amount") or 0),
            }
    print(f"   合併: {len(wallets)} 個唯一錢包")

    candidates = []
    for addr, d in wallets.items():
        if d["profit_30d"] < MIN_PROFIT_30D or d["volume_30d"] < MIN_VOLUME_30D:
            continue
        roi = d["profit_30d"] / d["volume_30d"] if d["volume_30d"] > 0 else 0.0
        candidates.append((roi, addr, d))
    candidates.sort(key=lambda x: x[0], reverse=True)
    print(
        f"   過濾 profit≥${MIN_PROFIT_30D:,.0f} & volume≥${MIN_VOLUME_30D:,.0f}: "
        f"{len(candidates)} 候選"
    )

    # 對照原版鯨魚清單（避免重複）
    orig_wallets: set[str] = set()
    if _ORIG_PATH.exists():
        with open(_ORIG_PATH, encoding="utf-8") as f:
            orig_wallets = {w["proxy_wallet"] for w in json.load(f)}
        print(f"   原版鯨魚: {len(orig_wallets)} 隻（一同納入顯示）")

    candidates = candidates[: MAX_WHALES * 3]

    print(
        f"\n🔍 驗證活躍度（value≥${MIN_VALUE_NOW:,.0f}, sports≤{MAX_SPORTS_RATIO:.0%}）"
    )
    now = int(time.time())
    seven_days_ago = now - 7 * 86400
    whales: list[Whale] = []
    new_count = 0

    for i, (roi, addr, d) in enumerate(candidates, 1):
        try:
            value_now = _fetch_value(addr)
            if value_now < MIN_VALUE_NOW:
                print(f"   [{i:2d}] {d['pseudonym'][:20]:20s} value=${value_now:>10,.0f}  ✗ 資金不足")
                continue
            trades = _fetch_trades(addr, limit=50)
            recent = [t for t in trades if int(t.get("timestamp", 0)) >= seven_days_ago]
            if len(recent) < MIN_TRADES_7D:
                print(f"   [{i:2d}] {d['pseudonym'][:20]:20s} 7d_trades={len(recent):3d}  ✗ 不夠活躍")
                continue

            breakdown = {"sports": 0, "crypto": 0, "politics": 0, "tech": 0, "other": 0}
            for t in trades:
                cat = classify(t.get("slug"), t.get("title"))
                breakdown[cat] = breakdown.get(cat, 0) + 1
            total = sum(breakdown.values()) or 1
            sports_ratio = breakdown["sports"] / total

            if sports_ratio > MAX_SPORTS_RATIO:
                print(
                    f"   [{i:2d}] {d['pseudonym'][:20]:20s} sports={sports_ratio:.0%}  ✗ 體育過多"
                )
                continue

            last_ts = max(int(t.get("timestamp", 0)) for t in recent)
            is_new = addr not in orig_wallets
            tag = "🆕 NEW" if is_new else "   舊"
            if is_new:
                new_count += 1

            whales.append(Whale(
                proxy_wallet=addr,
                pseudonym=d["pseudonym"],
                profit_30d=d["profit_30d"],
                volume_30d=d["volume_30d"],
                roi_30d=roi,
                wallet_value_now=value_now,
                recent_trade_count_7d=len(recent),
                last_trade_ts=last_ts,
                sports_ratio=sports_ratio,
                category_breakdown=breakdown,
            ))
            print(
                f"   [{i:2d}] {tag} {d['pseudonym'][:18]:18s} "
                f"roi={roi:6.1%} value=${value_now:>10,.0f} sports={sports_ratio:.0%} "
                f"p30d=${d['profit_30d']:,.0f}"
            )
            if len(whales) >= MAX_WHALES:
                break
        except Exception as e:
            print(f"   [{i:2d}] {d['pseudonym'][:20]:20s} ✗ API 失敗: {type(e).__name__}: {e}")
            continue

    return whales


def main() -> None:
    whales = discover_expanded()

    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_OUT_PATH, "w", encoding="utf-8") as f:
        json.dump([asdict(w) for w in whales], f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 60}")
    print(f" 結果摘要")
    print(f"{'=' * 60}")
    print(f"  共找到 {len(whales)} 隻鯨魚")

    # 原版鯨魚清單
    orig_wallets: set[str] = set()
    if _ORIG_PATH.exists():
        with open(_ORIG_PATH, encoding="utf-8") as f:
            orig_wallets = {w["proxy_wallet"] for w in json.load(f)}
    new_whales = [w for w in whales if w.proxy_wallet not in orig_wallets]
    print(f"  其中 {len(new_whales)} 隻為新增")
    print(f"  已存至: {_OUT_PATH}")

    if new_whales:
        print(f"\n  🆕 新增鯨魚清單：")
        for w in new_whales:
            print(
                f"    {w.pseudonym[:25]:25s}  profit30d=${w.profit_30d:>10,.0f}  "
                f"roi={w.roi_30d:.1%}  sports={w.sports_ratio:.0%}"
            )

    print(f"""
  💡 後續步驟：
  1. 若新增鯨魚 ≥ 3 隻，考慮替換 data/whales.json
     cp data/whales_expanded.json data/whales.json
  2. 重跑 backtest（需要先抓歷史訊號）：
     python -m scripts.run_backtest
  3. 比較擴大池後的 IS/OOS 差異是否更穩定
""")


if __name__ == "__main__":
    main()
