"""LIVE 上線就緒度檢查（只讀，不下單、不授權）。

檢查：
  1. 錢包 USDC 餘額 + MATIC gas
  2. USDC 對 CTF Exchange 的授權額度（不足則下單會失敗）
  3. 當前活躍的足球市場（價格甜區 0.55-0.80）可作驗證標的
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core  # noqa  DNS patch + UTF-8
sys.stdout.reconfigure(encoding="utf-8")

from core import config
from core.polygon_client import PolygonClient
from core.polymarket_client import PolymarketClient
from whale_copy.sport_classifier import sport_type
from trend_trade.market_matcher import _parse_json_list, _hours_until

print("="*64)
print("  🔍 LIVE 上線就緒度檢查")
print("="*64)

# ── 1. 餘額 + gas ───────────────────────────────────────────────
poly = PolygonClient()
usdc = poly.usdc_balance()
matic = poly.matic_balance()
print(f"\n[1] 錢包")
print(f"    地址      : {poly.address}")
print(f"    USDC      : ${usdc:.2f}")
print(f"    MATIC(gas): {matic:.3f}  {'✅' if matic > 0.5 else '⚠️ gas偏低'}")

# ── 2. USDC 授權 ────────────────────────────────────────────────
allowance = poly.usdc_allowance_for(config.POLYMARKET_CTF_EXCHANGE)
print(f"\n[2] USDC 授權給 CTF Exchange")
print(f"    當前額度  : ${allowance:,.2f}")
if allowance >= 20:
    print(f"    ✅ 足夠跑 $20 上限的實盤")
else:
    print(f"    ❌ 不足！下單前必須先 approve（python -m scripts.approve_usdc）")

# ── 3. 當前活躍足球市場（驗證標的）──────────────────────────────
print(f"\n[3] 當前活躍足球市場（價格甜區 0.55-0.80，可作 $2 驗證標的）")
client = PolymarketClient()
queries = ["World Cup", "soccer", "FIFA", "Premier League"]
seen = set()
found = 0
for q in queries:
    try:
        markets = client.search_markets(q, limit=20)
    except Exception as e:
        print(f"    ⚠️ 搜 '{q}' 失敗: {type(e).__name__}")
        continue
    for m in markets:
        cid = str(m.get("conditionId") or m.get("condition_id") or "")
        if cid in seen or not cid:
            continue
        seen.add(cid)
        if m.get("closed") or m.get("active") is False:
            continue
        title = m.get("question") or m.get("slug") or ""
        slug = m.get("slug") or ""
        if sport_type(slug, title) != "soccer":
            continue
        prices = _parse_json_list(m.get("outcomePrices"))
        hrs = _hours_until(m)
        if not prices or len(prices) != 2:
            continue
        try:
            p_yes = float(prices[0])
        except Exception:
            continue
        in_zone = 0.55 <= p_yes <= 0.80 or 0.55 <= (1 - p_yes) <= 0.80
        if in_zone and hrs > 1:
            found += 1
            print(f"    ✅ YES={p_yes:.2f}  剩{hrs:.0f}h  {title[:48]}")
            if found >= 6:
                break
    if found >= 6:
        break

if found == 0:
    print(f"    ⚠️ 暫無甜區活躍足球市場（世界盃 6/11 開賽後會大量出現）")

print(f"\n{'='*64}")
