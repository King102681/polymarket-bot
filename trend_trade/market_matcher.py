"""趨勢話題 → Polymarket 市場配對（免 API 規則版）。

流程：
  1. 關鍵字字典：中文話題 → 英文搜尋詞（覆蓋地緣/政治/宏觀/加密）
  2. 排除過濾：純娛樂/國內體育/地方新聞 → 直接跳過
  3. Gamma search：用英文 query 找活躍二元市場
  4. 選流動性最高的市場配對

不需要 Anthropic API key。
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from typing import Any

from core import config
from core.polymarket_client import PolymarketClient
from trend_trade.trend_fetcher import TrendItem

# ── 關鍵字對照表：中文詞組 → 英文搜尋詞 ─────────────────────────────────
# 按優先順序排列，第一個匹配到就用
KEYWORD_MAP: list[tuple[list[str], str]] = [
    # 美國政治
    (["川普", "特朗普", "trump"], "Trump"),
    (["拜登", "biden"], "Biden"),
    (["美國大選", "美國選舉", "總統選"], "US presidential election"),
    (["國會", "參議院", "眾議院"], "US Congress"),
    # 中美 / 台灣
    (["台灣", "台海", "兩岸", "台獨", "統一"], "Taiwan"),
    (["中美關係", "美中關係", "中美貿易"], "US China trade"),
    (["關稅", "貿易戰"], "US China tariffs"),
    (["習近平", "中共二十"], "China Xi"),
    # 中東
    (["以色列", "加沙", "哈馬斯", "巴勒斯坦"], "Israel Gaza ceasefire"),
    (["伊朗", "核武", "核協議", "核彈"], "Iran nuclear deal"),
    (["中東", "胡塞", "葉門", "沙烏地"], "Middle East"),
    (["霍爾木茲"], "Strait Hormuz"),
    # 俄烏
    (["烏克蘭", "俄羅斯", "俄烏", "普丁", "澤倫斯基"], "Russia Ukraine war"),
    (["停火協議", "和平協議"], "ceasefire peace deal"),
    # 北韓 / 東亞
    (["北韓", "金正恩", "核試"], "North Korea"),
    (["日本選舉", "日相", "岸田", "石破"], "Japan election"),
    (["南韓", "韓國選舉"], "South Korea"),
    # 總體經濟
    (["聯準會", "fed", "降息", "升息", "利率"], "Fed interest rate"),
    (["通膨", "CPI", "PCE"], "US inflation CPI"),
    (["衰退", "recession"], "US recession"),
    # 加密
    (["比特幣", "btc"], "Bitcoin price"),
    (["以太", "eth", "ethereum"], "Ethereum"),
    (["加密貨幣", "幣圈"], "crypto"),
    # 能源 / 商品
    (["石油", "原油", "opec"], "oil OPEC"),
    (["黃金", "gold"], "gold price"),
    # AI / 科技
    (["人工智能", "ai", "openai", "chatgpt", "gpt"], "AI artificial intelligence"),
    # 歐洲
    (["歐盟", "歐洲選舉", "德國選舉", "法國選舉"], "Europe election"),
    (["英國", "脫歐"], "UK Brexit"),
]

# ── 排除模式：這些話題在 Polymarket 幾乎找不到對應市場 ─────────────────
EXCLUDE_PATTERNS: list[str] = [
    # 娛樂 / 八卦
    "八卦", "緋聞", "離婚", "結婚", "懷孕", "藝人", "明星", "偶像",
    "綜藝", "電視劇", "電影票房", "網紅", "直播",
    # 國內體育比分（非預測市場）
    "進球", "比分", "冠軍賽季", "聯賽",
    # 中國地方民生
    "地鐵", "高鐵", "塌方", "火災", "颱風", "地震",
    # 其他
    "食安", "醫療", "疫情", "感冒",
]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _find_query(title: str) -> str | None:
    """回傳第一個匹配的英文搜尋詞；若應排除或無匹配則回傳 None。"""
    t = _normalize(title)
    # 排除清單優先
    for pat in EXCLUDE_PATTERNS:
        if pat in t:
            return None
    # 關鍵字匹配
    for keywords, query in KEYWORD_MAP:
        if any(kw in t for kw in keywords):
            return query
    return None


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
    """關鍵字匹配趨勢 → Polymarket 市場，不需要 AI API。"""
    client = client or PolymarketClient()
    pairs: list[tuple[TrendItem, dict]] = []

    for tr in trends:
        query = _find_query(tr.title)
        if not query:
            print(f"   ⏭️  跳過「{tr.title[:28]}」：不符政治/宏觀/地緣類別")
            continue

        try:
            markets = client.search_markets(query, limit=20)
        except Exception as e:
            print(f"   ⚠️ 搜尋 '{query}' 失敗: {type(e).__name__}")
            continue

        best = _pick_best(markets)
        if not best:
            print(f"   🔍 「{tr.title[:24]}」→ '{query}' 無合適市場")
            continue

        q = best.get("question") or best.get("slug") or ""
        print(f"   ✅ 「{tr.title[:24]}」→ {str(q)[:55]}")
        pairs.append((tr, best))

    return pairs
