"""趨勢話題 → Polymarket 市場配對。

流程：
  1. Claude（便宜模型）把中文熱門標題映射成英文搜尋關鍵字，並判斷是否
     對應到「可交易、且社媒可能領先定價」的 Polymarket 市場類型
     （政治/地緣/宏觀/中國相關）。不相關直接淘汰，省下後續成本。
  2. 用英文 query 打 Gamma public-search，挑出最佳二元（Yes/No）活躍市場。

回傳 (TrendItem, market_dict) 配對列表。
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

from core import config
from core.polymarket_client import PolymarketClient
from trend_trade import llm
from trend_trade.trend_fetcher import TrendItem

_MATCHER_SCHEMA = {
    "type": "object",
    "properties": {
        "relevant": {"type": "boolean"},
        "english_query": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
    },
    "required": ["relevant", "english_query", "keywords", "rationale"],
    "additionalProperties": False,
}

_MATCHER_SYSTEM = (
    "你是預測市場分析助手。輸入是一條來自中文社群/財經平台的熱門話題。\n"
    "Polymarket 的市場以英文為主，多為美國政治、地緣政治、總體經濟、加密，"
    "以及中國相關的全球事件。\n\n"
    "你的任務：\n"
    "1. 判斷這條中文話題是否可能對應到 Polymarket 上『可交易』的市場，"
    "且社群熱度有機會『領先』而非『落後』於該市場定價：\n"
    "   - 純中國國內娛樂、八卦、體育賽事比分、地方民生 → relevant=false。\n"
    "   - 美國大選、Fed 利率等『中文新聞通常落後西方』的題材 → 通常 relevant=false"
    "（除非是突發、全球同步事件）。\n"
    "   - 地緣衝突、戰爭、制裁、兩岸、重大宏觀/政策、全球市場事件 → 可能 relevant=true。\n"
    "2. 若 relevant=true，產生 1 個精簡英文搜尋詞（english_query）與數個關鍵字"
    "（keywords），用於在 Polymarket 搜尋對應市場。\n"
    "只回傳 JSON。"
)


def _hours_until(market: dict) -> float:
    end = market.get("endDate") or market.get("end_date_iso") or market.get("endDateIso")
    if not end:
        return 0.0
    try:
        dt = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        return (dt.timestamp() - time.time()) / 3600
    except Exception:
        return 0.0


def _parse_json_list(val: Any) -> list:
    """Gamma 常把 outcomes / clobTokenIds / outcomePrices 編成 JSON 字串。"""
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            v = json.loads(val)
            return v if isinstance(v, list) else []
        except Exception:
            return []
    return []


def _is_binary_active(market: dict) -> bool:
    if market.get("closed") or market.get("archived"):
        return False
    if market.get("active") is False:
        return False
    outcomes = [str(o).lower() for o in _parse_json_list(market.get("outcomes"))]
    return sorted(outcomes) == ["no", "yes"]


def _liquidity(market: dict) -> float:
    for k in ("liquidityNum", "liquidity", "liquidityClob"):
        v = market.get(k)
        try:
            if v is not None:
                return float(v)
        except Exception:
            pass
    return 0.0


def _pick_best(markets: list[dict]) -> dict | None:
    cands = [
        m for m in markets
        if _is_binary_active(m) and _hours_until(m) >= config.TREND_MIN_HOURS_LEFT
    ]
    if not cands:
        return None
    cands.sort(key=_liquidity, reverse=True)
    return cands[0]


def find_candidates(
    trends: list[TrendItem], client: PolymarketClient | None = None
) -> list[tuple[TrendItem, dict]]:
    client = client or PolymarketClient()
    pairs: list[tuple[TrendItem, dict]] = []

    for tr in trends:
        user = (
            f"熱門話題：{tr.title}\n"
            f"來源平台：{', '.join(tr.platforms)}（{tr.frequency} 個平台）\n"
            f"熱度：{tr.heat}/100，已追蹤 {tr.minutes_tracked} 分鐘，"
            f"排名上升：{'是' if tr.rank_improved else '否'}"
        )
        res = llm.call_json(
            model=config.TREND_MATCHER_MODEL,
            system=_MATCHER_SYSTEM,
            user=user,
            schema=_MATCHER_SCHEMA,
            max_tokens=512,
        )
        if not res or not res.get("relevant"):
            reason = (res or {}).get("rationale", "無回應")
            print(f"   ⏭️  跳過「{tr.title[:28]}」：{str(reason)[:50]}")
            continue

        query = str(res.get("english_query") or "").strip()
        if not query:
            continue
        markets = client.search_markets(query, limit=20)
        best = _pick_best(markets)
        if not best:
            print(f"   🔍 「{tr.title[:24]}」→ '{query}' 無合適市場")
            continue

        q = best.get("question") or best.get("slug")
        print(f"   ✅ 「{tr.title[:24]}」→ {str(q)[:50]}")
        pairs.append((tr, best))

    return pairs
