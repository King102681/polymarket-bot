"""從 newsnow（TrendRadar 的資料源）抓多平台熱門話題，計算粗略熱度。

TrendRadar 本身把 newsnow 結果存成本地檔再由 MCP 查詢；headless 管線改為
直接呼叫 newsnow 公開端點（免 key），自行計算熱度，避免額外跑常駐服務。
熱度權重近似 TrendRadar：排名 0.65 + 跨平台頻次 0.35。

會把這一輪快照存到 data/trend_state.json，用來推估話題「追蹤時長」與
「排名是否上升」——作為熱度加速（acceleration）的廉價代理。
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from core import config
from trend_trade import external_sources

NEWSNOW = "https://newsnow.busiyi.world/api/s"
_TIMEOUT = 15
# newsnow 會擋預設的 python-requests UA（回 403），需帶瀏覽器 UA。
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_STATE_PATH = _DATA_DIR / "trend_state.json"

PER_PLATFORM = 15          # 每平台取前 N 條
RANK_WEIGHT = 0.65
FREQ_WEIGHT = 0.35
FREQ_SATURATION = 3        # 出現在 3+ 平台即頻次滿分


@dataclass
class TrendItem:
    id: str                # 標準化標題的 key
    title: str
    platforms: list[str]
    best_rank: int
    frequency: int         # 出現在幾個平台
    heat: float            # 0-100
    url: str
    first_seen: int        # epoch 秒
    minutes_tracked: float # 距首次看到的分鐘數
    rank_improved: bool    # 相比上一輪排名是否上升


def _normalize(title: str) -> str:
    """去標點/空白、轉小寫，用來跨平台對齊同一話題。"""
    return re.sub(r"[^\w一-鿿]", "", title).lower()


def _extract_items(data: Any) -> list[dict]:
    """newsnow 各版本回傳結構略異，遞迴找出含 title 的 dict 列表。"""
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict) and x.get("title")]
    if isinstance(data, dict):
        for key in ("items", "data", "result", "list"):
            v = data.get(key)
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return [x for x in v if x.get("title")]
            if isinstance(v, dict):
                inner = _extract_items(v)
                if inner:
                    return inner
    return []


def _fetch_platform(pid: str) -> list[dict]:
    try:
        r = requests.get(f"{NEWSNOW}?id={pid}&latest", headers=_HEADERS, timeout=_TIMEOUT)
        r.raise_for_status()
        return _extract_items(r.json())[:PER_PLATFORM]
    except Exception as e:
        print(f"   ⚠️ newsnow {pid} 抓取失敗: {type(e).__name__}")
        return []


def _load_state() -> dict[str, dict]:
    if not _STATE_PATH.exists():
        return {}
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(items: list[TrendItem]) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state = {
        it.id: {"first_seen": it.first_seen, "best_rank": it.best_rank}
        for it in items
    }
    _STATE_PATH.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def fetch_trends(platforms: list[str] | None = None) -> list[TrendItem]:
    """抓取所有平台熱榜，聚合成 TrendItem（依熱度由高到低排序）。"""
    plats = platforms if platforms is not None else [
        p.strip() for p in config.TREND_PLATFORMS.split(",") if p.strip()
    ]
    now = int(time.time())

    # 聚合：normalized title -> {title, platforms, best_rank, url}
    agg: dict[str, dict] = {}
    for pid in plats:
        items = _fetch_platform(pid)
        for rank, it in enumerate(items, start=1):
            title = str(it.get("title", "")).strip()
            key = _normalize(title)
            if not key:
                continue
            rec = agg.setdefault(key, {
                "title": title,
                "platforms": set(),
                "best_rank": rank,
                "url": it.get("mobileUrl") or it.get("url") or "",
            })
            rec["platforms"].add(pid)
            rec["best_rank"] = min(rec["best_rank"], rank)
            if not rec["url"]:
                rec["url"] = it.get("mobileUrl") or it.get("url") or ""

    # 併入 newsnow 以外的英文政治/地緣 RSS 源（同一套去重/熱度流程）
    if config.TREND_EXTERNAL_ENABLED:
        for it in external_sources.fetch_external():
            title = str(it.get("title", "")).strip()
            key = _normalize(title)
            if not key:
                continue
            erank = it["rank"]
            rec = agg.setdefault(key, {
                "title": title,
                "platforms": set(),
                "best_rank": erank,
                "url": it.get("url") or "",
            })
            rec["platforms"].add(it["source"])
            rec["best_rank"] = min(rec["best_rank"], erank)
            if not rec["url"]:
                rec["url"] = it.get("url") or ""

    prev = _load_state()
    out: list[TrendItem] = []
    for key, rec in agg.items():
        best_rank = rec["best_rank"]
        freq = len(rec["platforms"])
        rank_score = max(0.0, 1.0 - (best_rank - 1) / PER_PLATFORM)
        freq_norm = min(freq / FREQ_SATURATION, 1.0)
        heat = round(100 * (RANK_WEIGHT * rank_score + FREQ_WEIGHT * freq_norm), 1)

        p = prev.get(key)
        first_seen = int(p["first_seen"]) if p and p.get("first_seen") else now
        minutes = round((now - first_seen) / 60, 1)
        improved = bool(p and best_rank < int(p.get("best_rank", 999)))

        out.append(TrendItem(
            id=key,
            title=rec["title"],
            platforms=sorted(rec["platforms"]),
            best_rank=best_rank,
            frequency=freq,
            heat=heat,
            url=rec["url"],
            first_seen=first_seen,
            minutes_tracked=minutes,
            rank_improved=improved,
        ))

    out.sort(key=lambda x: x.heat, reverse=True)
    _save_state(out)
    return out
