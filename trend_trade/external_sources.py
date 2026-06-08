"""newsnow 以外的英文政治／地緣趨勢源（RSS/Atom）。

newsnow 的英文源只有科技類（HN/GitHub/ProductHunt）；Polymarket 的大宗是美國政治
與地緣，這裡補上英文政治／世界新聞源。所有端點皆已實測可達（免 key）：
  - Reddit r/worldnews, r/politics（hot 排序＝社群熱度，最接近「trending」）
  - Politico（美國政治）
  - BBC World, Al Jazeera（世界／中東頭條）

回傳統一格式 [{title, url, source, rank}]，由 trend_fetcher 併入同一套去重／熱度流程。
每個來源獨立 try/except，單一來源失敗不影響其餘來源與 newsnow。
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import requests

_TIMEOUT = 20
_PER_FEED = 15  # 每來源取前 N 條（與 newsnow PER_PLATFORM 對齊，熱度尺度一致）
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

# (source_id, url)；皆為 RSS/Atom，已實測 HTTP 200
FEEDS: list[tuple[str, str]] = [
    ("reddit-worldnews", "https://www.reddit.com/r/worldnews/hot/.rss?limit=20"),
    ("reddit-politics", "https://www.reddit.com/r/politics/hot/.rss?limit=20"),
    ("politico", "https://rss.politico.com/politics-news.xml"),
    ("bbc-world", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("aljazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
]

# Reddit 置頂的版務／meta 貼文（非新聞），標題含這些字樣就略過
_REDDIT_SKIP = (
    "live thread", "megathread", "discussion thread", "cartoon thread",
    "weekly", "/r/", "subreddit", "moderator",
)


def _parse_feed(xml_text: str) -> list[dict]:
    """解析 RSS(<item>) 或 Atom(<entry>)，回傳 [{title, url}]（原順序）。"""
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return []
    for el in root.iter():  # 去命名空間，統一用 local tag
        el.tag = el.tag.rsplit("}", 1)[-1]
    nodes = root.findall(".//item") or root.findall(".//entry")
    out: list[dict] = []
    for nd in nodes:
        t_el = nd.find("title")
        title = (t_el.text or "").strip() if t_el is not None else ""
        if not title:
            continue
        l_el = nd.find("link")
        url = ""
        if l_el is not None:
            url = (l_el.text or l_el.get("href") or "").strip()
        out.append({"title": title, "url": url})
    return out


def _fetch_feed(source: str, url: str) -> list[dict]:
    try:
        r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        r.raise_for_status()
        items = _parse_feed(r.text)
    except Exception as e:
        print(f"   ⚠️ RSS {source} 抓取失敗: {type(e).__name__}")
        return []

    out: list[dict] = []
    rank = 0
    for it in items:
        title = it["title"]
        if source.startswith("reddit") and any(s in title.lower() for s in _REDDIT_SKIP):
            continue
        rank += 1
        if rank > _PER_FEED:
            break
        out.append({"title": title, "url": it["url"], "source": source, "rank": rank})
    return out


def fetch_external() -> list[dict]:
    """抓所有外部 RSS 源，回傳 [{title, url, source, rank}]。"""
    out: list[dict] = []
    for source, url in FEEDS:
        out.extend(_fetch_feed(source, url))
    return out
