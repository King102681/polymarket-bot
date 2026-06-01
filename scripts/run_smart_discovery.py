"""智慧鯨魚發現：專找「other 類別 + 進場價 0.20-0.80」的鯨魚。

除了傳統門檻，額外驗證：
  - other_ratio ≥ 30%（過去 50 筆中 other 市場的比例）
  - usable_price_ratio ≥ 25%（other 類別交易中，價格落在 0.20-0.80 的比例）

這直接對應 signal_generator 的 alpha 過濾，避免找到「跟不了」的鯨魚。

輸出：
  data/whales_smart.json         所有合格鯨魚
  data/whales.json               若找到 ≥ 2 隻新鯨魚則自動更新
"""
import json, sys, time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core  # noqa: F401  DNS patch + UTF-8

from whale_copy.discovery import Whale, _fetch_lb, _fetch_trades, _fetch_value
from whale_copy.market_classifier import classify

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_SMART_PATH  = _DATA_DIR / "whales_smart.json"
_WHALES_PATH = _DATA_DIR / "whales.json"

# ── 門檻 ─────────────────────────────────────────────────────────
LB_LIMIT        = 500      # leaderboard 每個抓 500 筆（更多候選）
MIN_PROFIT_30D  = 3_000    # 過去 30d 獲利 ≥ $3k
MIN_VOLUME_30D  = 15_000   # 過去 30d 交易量 ≥ $15k
MIN_VALUE_NOW   = 3_000    # 現有持倉價值 ≥ $3k（有資金在場）
MIN_TRADES_7D   = 2        # 過去 7 天至少 2 筆（非一次性）
MIN_OTHER_RATIO = 0.25     # other 類別 ≥ 25%
MIN_USABLE_RATIO= 0.20     # other 交易中，價格 0.20-0.80 的比例 ≥ 20%
MAX_WHALES      = 20
PRICE_LO, PRICE_HI = 0.20, 0.80


def _check_whale(i: int, addr: str, d: dict, seven_days_ago: int) -> Whale | None:
    name = d["pseudonym"][:22]
    try:
        value_now = _fetch_value(addr)
        if value_now < MIN_VALUE_NOW:
            print(f"   [{i:3d}] {name:22s}  value=${value_now:>9,.0f}  ✗ 資金不足")
            return None

        trades = _fetch_trades(addr, limit=50)
        recent = [t for t in trades if int(t.get("timestamp", 0)) >= seven_days_ago]
        if len(recent) < MIN_TRADES_7D:
            print(f"   [{i:3d}] {name:22s}  7d={len(recent):2d}筆          ✗ 不活躍")
            return None

        # 分類 + 價格分析
        breakdown = {"sports": 0, "crypto": 0, "politics": 0, "tech": 0, "other": 0}
        other_total, other_usable = 0, 0
        for t in trades:
            cat = classify(t.get("slug"), t.get("title"))
            breakdown[cat] = breakdown.get(cat, 0) + 1
            if cat == "other":
                other_total += 1
                price = float(t.get("price", 0) or 0)
                if PRICE_LO <= price <= PRICE_HI:
                    other_usable += 1

        total = sum(breakdown.values()) or 1
        other_ratio   = breakdown["other"] / total
        usable_ratio  = other_usable / other_total if other_total > 0 else 0.0

        if other_ratio < MIN_OTHER_RATIO:
            print(f"   [{i:3d}] {name:22s}  other={other_ratio:.0%}  ✗ other 太少")
            return None

        if usable_ratio < MIN_USABLE_RATIO:
            print(f"   [{i:3d}] {name:22s}  other={other_ratio:.0%}  usable={usable_ratio:.0%}  ✗ 進場價全 >0.80")
            return None

        roi = d["roi_30d"]
        last_ts = max(int(t.get("timestamp", 0)) for t in recent) if recent else 0
        print(
            f"   [{i:3d}] ✓ {name:22s}  roi={roi:6.1%}  "
            f"value=${value_now:>9,.0f}  other={other_ratio:.0%}  usable={usable_ratio:.0%}  "
            f"p30d=${d['profit_30d']:,.0f}"
        )
        return Whale(
            proxy_wallet=addr,
            pseudonym=d["pseudonym"],
            profit_30d=d["profit_30d"],
            volume_30d=d["volume_30d"],
            roi_30d=roi,
            wallet_value_now=value_now,
            recent_trade_count_7d=len(recent),
            last_trade_ts=last_ts,
            sports_ratio=breakdown["sports"] / total,
            category_breakdown=breakdown,
        )

    except Exception as e:
        print(f"   [{i:3d}] {name:22s}  ✗ API 失敗: {type(e).__name__}: {str(e)[:60]}")
        return None


def discover_smart() -> list[Whale]:
    print(f"📡 抓 leaderboard（30d, 各 {LB_LIMIT} 筆）...")
    profit_lb = _fetch_lb("profit", "30d", limit=LB_LIMIT)
    volume_lb = _fetch_lb("volume", "30d", limit=LB_LIMIT)
    print(f"   profit: {len(profit_lb)}    volume: {len(volume_lb)}")

    wallets: dict[str, dict] = {}
    for e in profit_lb:
        addr = e["proxyWallet"]
        wallets[addr] = {
            "pseudonym": e.get("pseudonym") or e.get("name") or "?",
            "profit_30d": float(e.get("amount") or 0),
            "volume_30d": 0.0,
            "roi_30d": 0.0,
        }
    for e in volume_lb:
        addr = e["proxyWallet"]
        vol = float(e.get("amount") or 0)
        if addr in wallets:
            wallets[addr]["volume_30d"] = vol
        else:
            wallets[addr] = {
                "pseudonym": e.get("pseudonym") or e.get("name") or "?",
                "profit_30d": 0.0, "volume_30d": vol, "roi_30d": 0.0,
            }

    # 計算 ROI，過濾基本門檻
    candidates = []
    for addr, d in wallets.items():
        if d["profit_30d"] < MIN_PROFIT_30D or d["volume_30d"] < MIN_VOLUME_30D:
            continue
        d["roi_30d"] = d["profit_30d"] / d["volume_30d"]
        candidates.append((d["roi_30d"], addr, d))
    candidates.sort(key=lambda x: -x[0])
    print(
        f"   profit≥${MIN_PROFIT_30D:,.0f} & vol≥${MIN_VOLUME_30D:,.0f}: "
        f"{len(candidates)} 候選（按 ROI 排序）"
    )

    # 已知鯨魚清單
    existing: set[str] = set()
    if _WHALES_PATH.exists():
        existing = {w["proxy_wallet"] for w in json.loads(_WHALES_PATH.read_text(encoding="utf-8"))}
    print(f"   現有 whales.json: {len(existing)} 隻")

    now = int(time.time())
    seven_days_ago = now - 7 * 86400
    whales: list[Whale] = []

    print(f"\n🔍 驗證（other≥{MIN_OTHER_RATIO:.0%}、usable≥{MIN_USABLE_RATIO:.0%}、"
          f"value≥${MIN_VALUE_NOW:,}）...")
    for i, (roi, addr, d) in enumerate(candidates, 1):
        w = _check_whale(i, addr, d, seven_days_ago)
        if w:
            whales.append(w)
        if len(whales) >= MAX_WHALES:
            break

    return whales, existing


def main():
    whales, existing = discover_smart()

    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _SMART_PATH.write_text(
        json.dumps([asdict(w) for w in whales], indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    new_whales = [w for w in whales if w.proxy_wallet not in existing]

    print(f"\n{'='*60}")
    print(f" 結果：{len(whales)} 隻合格  /  {len(new_whales)} 隻新增")
    print(f"{'='*60}")

    if new_whales:
        print("\n🆕 新鯨魚：")
        for w in new_whales:
            print(
                f"  {w.pseudonym[:28]:28s}  profit30d=${w.profit_30d:>10,.0f}  "
                f"roi={w.roi_30d:.1%}  other={w.category_breakdown.get('other',0)}/50"
            )

        # 若找到 ≥ 2 隻新鯨魚，合併進 whales.json
        if len(new_whales) >= 2:
            # 保留現有鯨魚（除了黑名單）
            BLACKLIST = {"0xbddf61af533ff524d27154e589d2d7a81510c684"}
            current = []
            if _WHALES_PATH.exists():
                current = [w for w in json.loads(_WHALES_PATH.read_text(encoding="utf-8"))
                           if w["proxy_wallet"] not in BLACKLIST]
            current_addrs = {w["proxy_wallet"] for w in current}

            merged = current + [asdict(w) for w in new_whales if w.proxy_wallet not in current_addrs]
            _WHALES_PATH.write_text(
                json.dumps(merged, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            print(f"\n✅ 已自動更新 data/whales.json（{len(current)} 舊 + {len(new_whales)} 新 = {len(merged)} 隻）")
        else:
            print(f"\n⚠️  新增 < 2 隻，whales.json 未自動更新。可手動選擇要加入的鯨魚。")
    else:
        print("\n⚠️  未找到新鯨魚，whales.json 不變。")

    print(f"\n已存至: {_SMART_PATH}")


if __name__ == "__main__":
    main()
