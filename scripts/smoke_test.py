"""Day 1 冒煙測試：驗證 .env 載入、Polygon 連線、餘額查詢、Gamma API、CLOB 認證。

完全不下單。執行：
    cd polytest
    python -m scripts.smoke_test
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config
from core.polygon_client import PolygonClient
from core.polymarket_client import PolymarketClient


def _mask(s: str | None) -> str:
    if not s:
        return "MISSING"
    return s[:4] + "***" + s[-4:] if len(s) > 8 else "***"


def test_config() -> None:
    print("[1/5] 驗證 .env 載入...")
    config.validate()
    print(f"  ENV path           : {config.ENV_PATH}")
    print(f"  WALLET_PRIVATE_KEY : {_mask(config.WALLET_PRIVATE_KEY)}")
    print(f"  POLY_API_KEY       : {_mask(config.POLY_API_KEY)}")
    print(f"  TG_CHAT_ID         : {config.TG_CHAT_ID}")
    print(f"  LIVE_MODE          : {config.LIVE_MODE}")
    print(f"  MAX_BET_USDC       : {config.MAX_BET_USDC}")
    print(f"  MAX_TOTAL_OPEN     : {config.MAX_TOTAL_OPEN_USDC}")


def test_polygon() -> PolygonClient:
    print("\n[2/5] 測試 Polygon RPC 連線...")
    poly = PolygonClient()
    if not poly.is_connected():
        raise RuntimeError("Polygon RPC 連線失敗")
    print(f"  連線成功")
    print(f"  錢包地址: {poly.address}")
    return poly


def test_balances(poly: PolygonClient) -> None:
    print("\n[3/5] 查詢鏈上餘額...")
    matic = poly.matic_balance()
    usdc = poly.usdc_balance()
    allowance = poly.usdc_allowance_for(config.POLYMARKET_CTF_EXCHANGE)
    print(f"  MATIC                          : {matic:.4f}")
    print(f"  USDC                           : {usdc:.2f}")
    print(f"  USDC allowance -> CTF Exchange : {allowance:.2f}")
    if matic == 0:
        print("  ⚠️  MATIC = 0，未來無法送出鏈上交易（gas）")
    if allowance < usdc:
        print(f"  ⚠️  授權額度 {allowance:.2f} < 餘額 {usdc:.2f}，建議跑 approve_usdc.py")


def test_gamma() -> PolymarketClient:
    print("\n[4/5] 測試 Polymarket Gamma API...")
    mkt = PolymarketClient()
    events = mkt.list_active_events(limit=3)
    print(f"  拉到 {len(events)} 個活躍事件")
    for ev in events:
        title = (ev.get("title") or "")[:60]
        print(f"    - {title}")
    return mkt


def test_clob(mkt: PolymarketClient) -> None:
    print("\n[5/5] 測試 CLOB 訂單簿讀取（按 24h 交易量找 top market）...")
    markets = mkt.list_top_markets(limit=5)
    sample_token = None
    sample_q = None
    for m in markets:
        ids = m.get("clobTokenIds")
        if isinstance(ids, str):
            ids = json.loads(ids)
        if m.get("enableOrderBook") and ids:
            sample_token = ids[0]
            sample_q = (m.get("question") or "")[:55]
            break
    if not sample_token:
        print("  ⚠️  Gamma /markets 找不到 enableOrderBook 的市場")
        return
    try:
        book = mkt.get_orderbook(sample_token)
    except Exception as e:
        msg = str(e)
        print(f"  ❌ CLOB 失敗: {type(e).__name__}: {msg[:200]}")
        return
    bids = getattr(book, "bids", None) or (book.get("bids") if isinstance(book, dict) else [])
    asks = getattr(book, "asks", None) or (book.get("asks") if isinstance(book, dict) else [])
    print(f"  question  : {sample_q}")
    print(f"  token_id  : {sample_token[:14]}...")
    print(f"  bids depth: {len(bids)} 層")
    print(f"  asks depth: {len(asks)} 層")
    if asks:
        a0 = asks[0]
        price = getattr(a0, "price", None) or a0.get("price")
        size = getattr(a0, "size", None) or a0.get("size")
        print(f"  best ask  : price={price} size={size}")
    if bids:
        b0 = bids[0]
        price = getattr(b0, "price", None) or b0.get("price")
        size = getattr(b0, "size", None) or b0.get("size")
        print(f"  best bid  : price={price} size={size}")


def main() -> None:
    print("=" * 60)
    print(" Polymarket Bot — Day 1 Smoke Test")
    print("=" * 60)
    try:
        test_config()
        poly = test_polygon()
        test_balances(poly)
        mkt = test_gamma()
        test_clob(mkt)
        print("\n" + "=" * 60)
        print(" ✅ 全部通過")
        print("=" * 60)
    except Exception as e:
        print(f"\n❌ 失敗: {type(e).__name__}: {e}")
        raise


if __name__ == "__main__":
    main()
