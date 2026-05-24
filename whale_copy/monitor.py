"""鯨魚監控：每次呼叫掃描一輪，找出「上次檢查之後」的新 BUY 單。

狀態：
  - data/monitor_state.json   每隻鯨魚的 last seen timestamp
  - data/signals.jsonl        新訊號 append-only log

外部用排程器（cron / Windows Task Scheduler / Claude /loop）每 10 分鐘呼叫一次。
"""
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import requests

from whale_copy import discovery

DATA_BASE = "https://data-api.polymarket.com"
_TIMEOUT = 15
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_STATE_PATH = _DATA_DIR / "monitor_state.json"
_SIGNALS_PATH = _DATA_DIR / "signals.jsonl"

# 首次見到某錢包時，從這時間前的交易視為「歷史」不發訊號
_INITIAL_LOOKBACK_SEC = 6 * 3600


@dataclass
class Signal:
    detected_at: int
    whale_wallet: str
    whale_pseudonym: str
    trade_ts: int
    side: str
    market_title: str
    market_slug: str
    condition_id: str
    asset: str
    outcome: str
    outcome_index: int
    whale_price: float
    whale_size: float
    transaction_hash: str


def _load_state() -> dict:
    if _STATE_PATH.exists():
        with open(_STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"last_seen_ts": {}, "last_run_ts": 0}


def _save_state(state: dict) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _fetch_trades(wallet: str, limit: int = 50) -> list[dict]:
    r = requests.get(
        f"{DATA_BASE}/trades",
        params={"user": wallet, "limit": limit},
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def _append_signals(signals: list[Signal]) -> None:
    _SIGNALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_SIGNALS_PATH, "a", encoding="utf-8") as f:
        for s in signals:
            f.write(json.dumps(asdict(s), ensure_ascii=False) + "\n")


def scan_once(
    initial_lookback_sec: int = _INITIAL_LOOKBACK_SEC,
    trades_limit: int = 50,
    force_lookback: bool = False,
) -> list[Signal]:
    """一次掃描：拉所有鯨魚最新 trades，找新 BUY，append 訊號。

    initial_lookback_sec：首次見到該錢包時回看多久（state 已存就不適用）
    trades_limit       ：每次拉的 trades 上限（鯨魚很活躍時要調大）
    force_lookback     ：True 時強制把每隻鯨魚的 last_seen 重設為 now - initial_lookback_sec
    """
    whales = discovery.load()
    if not whales:
        print("⚠️  whales.json 是空的，先跑 scripts/run_whale_discovery.py")
        return []

    state = _load_state()
    now = int(time.time())
    initial_baseline = now - initial_lookback_sec
    if force_lookback:
        for w in whales:
            state["last_seen_ts"][w.proxy_wallet] = initial_baseline

    new_signals: list[Signal] = []
    print(f"🔍 輪詢 {len(whales)} 隻鯨魚 [{time.strftime('%Y-%m-%d %H:%M:%S')}]")
    for w in whales:
        last_seen = state["last_seen_ts"].get(w.proxy_wallet, initial_baseline)
        try:
            trades = _fetch_trades(w.proxy_wallet, limit=trades_limit)
        except Exception as e:
            print(f"  ✗ {w.pseudonym[:18]:18s} 抓失敗: {type(e).__name__}")
            continue

        new_buys = [
            t for t in trades
            if int(t.get("timestamp", 0)) > last_seen
            and (t.get("side") or "").upper() == "BUY"
        ]

        for t in new_buys:
            new_signals.append(Signal(
                detected_at=now,
                whale_wallet=w.proxy_wallet,
                whale_pseudonym=w.pseudonym,
                trade_ts=int(t.get("timestamp", 0)),
                side=t.get("side", ""),
                market_title=t.get("title", ""),
                market_slug=t.get("slug", ""),
                condition_id=t.get("conditionId", ""),
                asset=t.get("asset", ""),
                outcome=t.get("outcome", ""),
                outcome_index=int(t.get("outcomeIndex") or 0),
                whale_price=float(t.get("price") or 0),
                whale_size=float(t.get("size") or 0),
                transaction_hash=t.get("transactionHash", ""),
            ))

        max_ts_in_batch = max(
            (int(t.get("timestamp", 0)) for t in trades),
            default=last_seen,
        )
        state["last_seen_ts"][w.proxy_wallet] = max(last_seen, max_ts_in_batch)

        marker = f"+{len(new_buys)}" if new_buys else "·"
        print(f"  {marker:>4} {w.pseudonym[:18]:18s}")

    state["last_run_ts"] = now
    _save_state(state)

    if new_signals:
        _append_signals(new_signals)
        print(f"\n📥 共 {len(new_signals)} 筆新訊號 → data/signals.jsonl")
    else:
        print(f"\n📭 本輪 0 筆新訊號")

    return new_signals
