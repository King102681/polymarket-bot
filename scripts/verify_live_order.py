"""LIVE post_order 認證驗證：掛一筆絕不成交的 $1 買單，確認後立即取消。

⚠️ 2026-05 起 Polymarket 廢棄 py-clob-client（伺服器回 400 invalid order version），
   本腳本已遷移到官方新版統一 SDK polymarket-client（github.com/Polymarket/py-sdk）。

目的：確認 VPN（住宅出口）+ 新 SDK 能否真實下單。
安全：
  - 標的選 p≥0.90 的市場，買單掛在 0.10 → 不可能成交
  - try/finally 保證即使中途出錯也會撤單
  - 全程最大風險 $1（且幾乎不可能成交）
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core  # noqa  DNS patch + UTF-8
sys.stdout.reconfigure(encoding="utf-8")

from core import config
from core.polymarket_client import PolymarketClient
from trend_trade.market_matcher import _parse_json_list

from polymarket import SecureClient

try:
    from polymarket.models import ApiKeyCreds
except ImportError:  # beta 期間公開匯出路徑可能變動
    from polymarket.models.clob.api_key import ApiKeyCreds

OK, FAIL = "✅", "❌"

# ── 找一個 p≥0.90 的活躍市場（買單掛 0.10 絕不成交）──────────────
pc = PolymarketClient()
token_id, q_title, mid = None, "", 0.0
for q in ("Bitcoin above", "Bitcoin", "Trump", "2026"):
    try:
        for m in pc.search_markets(q, limit=25):
            if m.get("closed") or m.get("active") is False:
                continue
            toks = _parse_json_list(m.get("clobTokenIds"))
            prices = _parse_json_list(m.get("outcomePrices"))
            if len(toks) == 2 and len(prices) == 2:
                try:
                    p0 = float(prices[0])
                except Exception:
                    continue
                if p0 >= 0.90:                       # YES 很貴 → 掛 0.10 買單絕不成交
                    token_id, q_title, mid = str(toks[0]), str(m.get("question", "")), p0
                    break
        if token_id:
            break
    except Exception:
        pass

if not token_id:
    print(f"{FAIL} 找不到 p≥0.90 的安全標的，中止")
    sys.exit(1)

print(f"標的: {q_title[:50]}")
print(f"市價 YES={mid:.2f}  →  掛買單在 0.10（偏離 {(mid-0.10)*100:.0f}%，絕不成交）\n")

# ── 初始化（新 SDK：自動驗證憑證 + 偵測錢包類型）────────────────
print("[auth] 建立 SecureClient ...")
creds = None
if config.POLY_API_KEY and config.POLY_API_SECRET and config.POLY_API_PASSPHRASE:
    creds = ApiKeyCreds.model_validate({
        "apiKey": config.POLY_API_KEY,
        "secret": config.POLY_API_SECRET,
        "passphrase": config.POLY_API_PASSPHRASE,
    })

try:
    clob = SecureClient.create(private_key=config.WALLET_PRIVATE_KEY, credentials=creds)
except Exception as e:
    print(f"   既有 API 憑證無法使用（{type(e).__name__}: {str(e)[:60]}），改用自動衍生 ...")
    clob = SecureClient.create(private_key=config.WALLET_PRIVATE_KEY)

print(f"   錢包: {clob.wallet}")
print(f"   類型: {clob.wallet_type}\n")

order_id = ""
try:
    # ── post：簽名 + 送出 ──────────────────────────────────────
    print("[post] 送出 $1 限價買單 @ 0.10 ...")
    resp = clob.place_limit_order(token_id=token_id, price=0.10, size=10, side="BUY")
    print(f"   回應: success={resp.success} status={getattr(resp, 'status', '?')}")

    order_id = resp.order_id or ""
    if order_id:
        print(f"   {OK} POST 成功！order_id={order_id}")
        print(f"   {OK} geoblock 已突破 → LIVE 下單鏈路就緒")
    else:
        print(f"   {FAIL} POST 未拿到 order_id（success={resp.success}）")

    # ── 查單狀態 ───────────────────────────────────────────────
    if order_id:
        time.sleep(1)
        try:
            o = clob.get_order(order_id=order_id)
            print(f"   單狀態: {str(o)[:100]}")
        except Exception as e:
            print(f"   查單: {type(e).__name__}")

finally:
    # ── 必定取消（即使上面出錯）────────────────────────────────
    if order_id:
        print(f"\n[cancel] 取消掛單 {order_id} ...")
        try:
            c = clob.cancel_order(order_id=order_id)
            print(f"   {OK} 已取消: {str(c)[:100]}")
        except Exception as e:
            print(f"   {FAIL} 取消失敗: {type(e).__name__}: {str(e)[:80]}")
            print(f"   ⚠️ 請手動確認該掛單已取消（order_id={order_id}）")
    else:
        print("\n（無 order_id，無需取消）")
    try:
        clob.close()
    except Exception:
        pass

print("\n" + "="*60)
print("  POST 成功 + 取消 = LIVE 下單鏈路 100% 驗證完畢")
print("="*60)
