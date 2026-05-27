"""拉每隻認可鯨魚過去 N 天 BUY trades，並查對應市場的結算狀態。

輸出：
  - data/backtest/trades_<wallet_pseudonym>.jsonl    # 該鯨魚 BUY 列表
  - data/backtest/markets_resolved.json              # condition_id → market dict
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from whale_copy import discovery

DATA_BASE = "https://data-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
_TIMEOUT = 12
_WORKERS = 10          # 同時查 10 個市場（並行）
_BACKTEST_DIR = Path(__file__).resolve().parent.parent / "data" / "backtest"
_MARKETS_PATH = _BACKTEST_DIR / "markets_resolved.json"


def _fetch_trades_page(wallet: str, limit: int, offset: int) -> list[dict]:
    r = requests.get(
        f"{DATA_BASE}/trades",
        params={"user": wallet, "limit": limit, "offset": offset},
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def fetch_all_trades(wallet: str, since_ts: int) -> list[dict]:
    """分頁拉 trades 直到時間早於 since_ts。trades 預設按時間倒序"""
    all_trades: list[dict] = []
    offset = 0
    page_size = 500
    while True:
        page = _fetch_trades_page(wallet, page_size, offset)
        if not page:
            break
        all_trades.extend(page)
        oldest = min((int(t.get("timestamp", 0)) for t in page), default=0)
        if oldest < since_ts:
            break
        if len(page) < page_size:
            break
        offset += page_size
        if offset > 5000:
            break
    return [t for t in all_trades if int(t.get("timestamp", 0)) >= since_ts]


def _fetch_market_clob(condition_id: str) -> dict | None:
    """CLOB /markets/{cid}：永遠回，含已結算（closed=true）市場，token.winner 標記贏家"""
    r = requests.get(f"{CLOB_BASE}/markets/{condition_id}", timeout=_TIMEOUT)
    if r.status_code != 200:
        return None
    return r.json()


def fetch_markets_for_conditions(condition_ids: list[str]) -> dict[str, dict]:
    unique = sorted(set(condition_ids))

    # ── 快取：載入已有的結果，只查缺少的 ──────────────────────────────
    cached: dict[str, dict] = {}
    if _MARKETS_PATH.exists():
        with open(_MARKETS_PATH, encoding="utf-8") as f:
            cached = json.load(f)
        already = len(cached)
    else:
        already = 0

    to_fetch = [cid for cid in unique if cid not in cached]
    print(
        f"   查 {len(unique)} 個唯一市場（快取 {already} / 新查 {len(to_fetch)}）..."
    )

    if not to_fetch:
        return {cid: cached[cid] for cid in unique if cid in cached}

    # ── 並行查詢（ThreadPoolExecutor，最多 _WORKERS 個同時進行）──────
    out: dict[str, dict] = dict(cached)  # 從快取開始
    done = 0

    def _fetch(cid: str) -> tuple[str, dict | None]:
        return cid, _fetch_market_clob(cid)

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = {pool.submit(_fetch, cid): cid for cid in to_fetch}
        for fut in as_completed(futures):
            done += 1
            cid, m = fut.result()
            if m:
                out[cid] = m
            if done % 100 == 0 or done == len(to_fetch):
                print(f"   ...{done}/{len(to_fetch)} 新市場查詢完成")

    return out


def pull_all(lookback_days: int = 90) -> None:
    _BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    whales = discovery.load()
    if not whales:
        print("⚠️  whales.json 空，先跑 run_whale_discovery.py")
        return
    since_ts = int(time.time()) - lookback_days * 86400

    all_cids: set[str] = set()
    for w in whales:
        print(f"\n📡 {w.pseudonym} 過去 {lookback_days} 天 trades...")
        trades = fetch_all_trades(w.proxy_wallet, since_ts)
        buys = [t for t in trades if (t.get("side") or "").upper() == "BUY"]
        path = _BACKTEST_DIR / f"trades_{w.pseudonym}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for t in buys:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")
        print(f"   抓到 {len(trades)} 筆全部 trades，BUY {len(buys)} 筆 → {path.name}")
        for t in buys:
            cid = t.get("conditionId")
            if cid:
                all_cids.add(cid)

    print(f"\n📡 查所有 {len(all_cids)} 個 condition_id 的結算狀態...")
    markets = fetch_markets_for_conditions(list(all_cids))
    with open(_MARKETS_PATH, "w", encoding="utf-8") as f:
        json.dump(markets, f, indent=2, ensure_ascii=False)
    closed = sum(1 for m in markets.values() if m.get("closed"))
    print(f"   {len(markets)} 個市場（已結算 {closed} / 仍進行中 {len(markets) - closed}）")
