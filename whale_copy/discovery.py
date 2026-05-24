"""鯨魚發現：抓 Polymarket leaderboard → 過濾門檻 → 用 Data API 驗證活躍度。

資料源：
  - lb-api.polymarket.com/profit?window=30d  過去 30 天累計獲利
  - lb-api.polymarket.com/volume?window=30d  過去 30 天累計交易量
  - data-api.polymarket.com/trades  該錢包近期交易（驗證 7 天活躍度）
  - data-api.polymarket.com/value   該錢包當前總價值

輸出：data/whales.json
"""
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests

from whale_copy.market_classifier import classify

LB_BASE = "https://lb-api.polymarket.com"
DATA_BASE = "https://data-api.polymarket.com"
_TIMEOUT = 15
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_WHALES_PATH = _DATA_DIR / "whales.json"


@dataclass
class Whale:
    proxy_wallet: str
    pseudonym: str
    profit_30d: float
    volume_30d: float
    roi_30d: float
    wallet_value_now: float = 0.0
    recent_trade_count_7d: int = 0
    last_trade_ts: int = 0
    sports_ratio: float = 0.0           # 過去 50 筆中體育類佔比
    category_breakdown: dict[str, int] = None  # {sports: N, crypto: N, politics: N, tech: N, other: N}


def _get(url: str, params: dict[str, Any]) -> Any:
    r = requests.get(url, params=params, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _fetch_lb(kind: str, window: str = "30d", limit: int = 100) -> list[dict]:
    return _get(f"{LB_BASE}/{kind}", {"window": window, "limit": limit})


def _fetch_trades(wallet: str, limit: int = 50) -> list[dict]:
    return _get(f"{DATA_BASE}/trades", {"user": wallet, "limit": limit})


def _fetch_value(wallet: str) -> float:
    data = _get(f"{DATA_BASE}/value", {"user": wallet})
    if isinstance(data, list) and data:
        return float(data[0].get("value", 0.0))
    return 0.0


def discover(
    max_whales: int = 20,
    min_profit_30d: float = 10_000,
    min_volume_30d: float = 50_000,
    min_value_now: float = 10_000,
    min_trades_7d: int = 1,
    max_sports_ratio: float = 0.5,
) -> list[Whale]:
    """合併 profit + volume 排行，過濾門檻並驗證 7 天活躍度。

    max_sports_ratio：過去 50 筆中體育類佔比上限。設 1.0 等於不過濾。
    """
    print(f"📡 抓 leaderboard（window=30d, 各 100 筆）")
    profit_lb = _fetch_lb("profit", "30d", limit=100)
    volume_lb = _fetch_lb("volume", "30d", limit=100)
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

    candidates: list[tuple[float, str, dict]] = []
    for addr, d in wallets.items():
        if d["profit_30d"] < min_profit_30d or d["volume_30d"] < min_volume_30d:
            continue
        roi = d["profit_30d"] / d["volume_30d"] if d["volume_30d"] > 0 else 0.0
        candidates.append((roi, addr, d))
    candidates.sort(key=lambda x: x[0], reverse=True)
    print(
        f"   過濾 profit≥${min_profit_30d:,.0f} & volume≥${min_volume_30d:,.0f}: "
        f"{len(candidates)} 候選"
    )

    candidates = candidates[: max_whales * 3]  # 預留剔除空間

    print(
        f"\n🔍 用 Data API 驗證活躍度（7d ≥ {min_trades_7d} & value ≥ ${min_value_now:,.0f} "
        f"& sports_ratio ≤ {max_sports_ratio:.0%}）"
    )
    now = int(time.time())
    seven_days_ago = now - 7 * 86400
    whales: list[Whale] = []
    for i, (roi, addr, d) in enumerate(candidates, 1):
        try:
            value_now = _fetch_value(addr)
            if value_now < min_value_now:
                print(f"   [{i:2d}] {d['pseudonym'][:18]:18s} value=${value_now:>10,.0f}  ✗ 資金不足")
                continue
            trades = _fetch_trades(addr, limit=50)
            recent = [t for t in trades if int(t.get("timestamp", 0)) >= seven_days_ago]
            if len(recent) < min_trades_7d:
                print(f"   [{i:2d}] {d['pseudonym'][:18]:18s} 7d_trades={len(recent):3d}  ✗ 不夠活躍")
                continue

            # 分類過去 50 筆，計算各類佔比
            breakdown = {"sports": 0, "crypto": 0, "politics": 0, "tech": 0, "other": 0}
            for t in trades:
                cat = classify(t.get("slug"), t.get("title"))
                breakdown[cat] = breakdown.get(cat, 0) + 1
            total = sum(breakdown.values()) or 1
            sports_ratio = breakdown["sports"] / total
            if sports_ratio > max_sports_ratio:
                print(
                    f"   [{i:2d}] {d['pseudonym'][:18]:18s} sports={sports_ratio:.0%} "
                    f"({breakdown}) ✗ 體育過多"
                )
                continue

            last_ts = max(int(t.get("timestamp", 0)) for t in recent)
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
                f"   [{i:2d}] {d['pseudonym'][:18]:18s} ✓ roi={roi:6.1%} "
                f"value=${value_now:>10,.0f} sports={sports_ratio:.0%} {breakdown}"
            )
            if len(whales) >= max_whales:
                break
        except Exception as e:
            print(f"   [{i:2d}] {d['pseudonym'][:18]:18s} ✗ Data API 失敗: {type(e).__name__}")
            continue

    return whales


def save(whales: list[Whale], path: Path = _WHALES_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(w) for w in whales], f, indent=2, ensure_ascii=False)
    print(f"\n💾 已存 {path} （{len(whales)} 隻鯨魚）")


def load(path: Path = _WHALES_PATH) -> list[Whale]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [Whale(**d) for d in json.load(f)]
