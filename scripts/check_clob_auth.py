"""CLOB 下單鏈路驗證（用 0.34.6 正確 API，簽名但不送出，免費）。

關卡：
  1. import（修正後：OrderArgs / OrderType / order_builder.constants.BUY）
  2. ClobClient 初始化 + L2 認證
  3. 連線
  4. 取活躍市場 token_id + tick size
  5. create_order：簽名一筆限價單（不 post，不花錢）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core  # noqa  DNS patch + UTF-8
sys.stdout.reconfigure(encoding="utf-8")

from core import config

OK, FAIL = "✅", "❌"

# ── 關卡 1：import（executor 修正後的路徑）──────────────────────
print("[1] import（0.34.6 正確路徑）...")
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY
    print(f"    {OK} ClobClient / OrderArgs / OrderType / BUY 全部 import 成功")
except Exception as e:
    print(f"    {FAIL} import 失敗: {e}")
    sys.exit(1)

# ── 關卡 2：初始化 + 認證 ──────────────────────────────────────
print("\n[2] ClobClient 初始化 + set_api_creds...")
try:
    clob = ClobClient(host="https://clob.polymarket.com",
                      key=config.WALLET_PRIVATE_KEY, chain_id=config.CHAIN_ID)
    clob.set_api_creds(ApiCreds(
        api_key=config.POLY_API_KEY,
        api_secret=config.POLY_API_SECRET,
        api_passphrase=config.POLY_API_PASSPHRASE,
    ))
    print(f"    {OK} 成功（錢包 {clob.get_address()}）")
except Exception as e:
    print(f"    {FAIL} {type(e).__name__}: {e}")
    sys.exit(1)

# ── 關卡 3：連線 ───────────────────────────────────────────────
print("\n[3] 連線...")
try:
    print(f"    {OK} get_ok={clob.get_ok()}  server_time={clob.get_server_time()}")
except Exception as e:
    print(f"    ·  {type(e).__name__}")

# ── 關卡 4：取活躍市場 token_id + tick ─────────────────────────
print("\n[4] 取活躍市場 token_id...")
from core.polymarket_client import PolymarketClient
from trend_trade.market_matcher import _parse_json_list
pc = PolymarketClient()
token_id, mid_price = None, 0.5
for q in ("Bitcoin", "Trump", "election"):
    try:
        for m in pc.search_markets(q, limit=20):
            if m.get("closed") or m.get("active") is False:
                continue
            toks = _parse_json_list(m.get("clobTokenIds"))
            prices = _parse_json_list(m.get("outcomePrices"))
            if len(toks) == 2 and len(prices) == 2:
                token_id = str(toks[0])
                try:
                    mid_price = round(float(prices[0]), 2)
                except Exception:
                    pass
                print(f"    {OK} {str(m.get('question'))[:40]}  p={mid_price}")
                break
        if token_id:
            break
    except Exception:
        pass
if not token_id:
    print(f"    {FAIL} 找不到活躍市場")
    sys.exit(1)

try:
    tick = clob.get_tick_size(token_id)
    print(f"    {OK} tick_size={tick}")
except Exception as e:
    tick = 0.01
    print(f"    ·  get_tick_size 失敗（用 0.01）: {type(e).__name__}")

# ── 關卡 5：簽名（不 post）────────────────────────────────────
print("\n[5] create_order 簽名一筆 $1 限價單（不送出）...")
# 掛在極低價（0.10），即使誤送也不會成交
safe_price = 0.10
size = round(1.0 / safe_price, 2)
try:
    args = OrderArgs(price=safe_price, size=size, side=BUY, token_id=token_id)
    signed = clob.create_order(args)
    print(f"    {OK} 簽名成功！EIP712 + 私鑰簽名鏈路完全 OK")
    print(f"       price={safe_price} size={size}  → LIVE 只差 post_order 送出")
except Exception as e:
    print(f"    {FAIL} 簽名失敗: {type(e).__name__}: {str(e)[:90]}")

print("\n" + "="*60)
print("  簽名 OK = 下單核心就緒。401 疑慮需用 post 不成交單確認")
print("="*60)
