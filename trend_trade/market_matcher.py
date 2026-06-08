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
    # 關鍵字以「簡體大陸詞優先 + 繁體 + 英文」三種寫法並列（newsnow 回簡體）；
    # 英文只用夠長夠 specific 的詞，避免 substring 誤判（不可用 ai/eth/eu/uk/fed）。
    # ── 美國政治 ──
    (["特朗普", "川普", "trump"], "Trump"),
    (["拜登", "biden"], "Biden"),
    (["贺锦丽", "賀錦麗", "哈里斯", "harris"], "Kamala Harris"),
    (["万斯", "萬斯", "vance"], "JD Vance"),
    (["美国大选", "美國大選", "美国总统", "美國總統", "总统选举", "presidentialelection"], "US presidential election"),
    (["国会", "國會", "参议院", "參議院", "众议院", "眾議院", "congress", "senate"], "US Congress"),
    (["最高法院", "supremecourt", "scotus"], "US Supreme Court"),
    (["政府关门", "政府關門", "shutdown", "债务上限", "債務上限", "debtceiling"], "US government shutdown"),
    # ── 中美 / 台灣 ──
    (["台湾", "台灣", "台海", "两岸", "兩岸", "台独", "台獨", "taiwan"], "Taiwan China"),
    (["关税", "關稅", "贸易战", "貿易戰", "tariff"], "US China tariffs"),
    (["习近平", "習近平", "xijinping"], "China Xi Jinping"),
    (["中美", "美中", "uschina", "chinaus"], "US China relations"),
    # ── 中東 ──
    (["以色列", "加沙", "哈马斯", "哈馬斯", "巴勒斯坦", "israel", "gaza", "hamas"], "Israel Gaza ceasefire"),
    (["伊朗", "核协议", "核協議", "iran"], "Iran nuclear deal"),
    (["黎巴嫩", "真主党", "真主黨", "hezbollah"], "Hezbollah Lebanon"),
    (["也门", "葉門", "胡塞", "houthi"], "Houthi Yemen"),
    (["叙利亚", "敘利亞", "syria"], "Syria"),
    # ── 俄烏 ──
    (["乌克兰", "烏克蘭", "俄罗斯", "俄羅斯", "俄乌", "俄烏", "普京", "普丁", "泽连斯基", "澤倫斯基", "ukraine", "russia", "putin", "zelensky"], "Russia Ukraine war"),
    (["停火", "停战", "停戰", "和平协议", "和平協議", "ceasefire"], "ceasefire peace deal"),
    # ── 北韓 / 東亞 ──
    (["朝鲜", "朝鮮", "北韓", "金正恩", "northkorea", "kimjong"], "North Korea"),
    (["韩国", "韓國", "南韓", "尹锡悦", "李在明", "southkorea"], "South Korea"),
    (["日本首相", "高市", "石破", "日本大选", "japanelection", "japanpm"], "Japan election"),
    # ── 總體經濟 ──
    (["美联储", "聯準會", "联储", "鲍威尔", "鮑威爾", "powell", "federalreserve"], "Fed interest rate"),
    (["降息", "加息", "升息", "利率", "ratecut", "ratehike", "interestrate"], "Fed interest rate"),
    (["通胀", "通膨", "cpi", "inflation"], "US inflation CPI"),
    (["衰退", "recession", "非农", "非農", "nonfarm"], "US recession"),
    # ── 加密 ──
    (["比特币", "比特幣", "bitcoin", "btc"], "Bitcoin price"),
    (["以太坊", "ethereum"], "Ethereum"),
    (["加密货币", "加密貨幣", "币圈", "幣圈", "crypto", "solana"], "crypto"),
    # ── 能源 / 商品 ──
    (["石油", "原油", "opec", "crudeoil"], "oil price"),
    (["黄金", "黃金", "goldprice"], "gold price"),
    # ── AI / 科技 ──
    (["openai", "chatgpt", "altman", "gpt-"], "OpenAI"),
    (["anthropic", "claude"], "Anthropic"),
    (["gemini", "deepmind"], "Google Gemini"),
    (["英伟达", "輝達", "nvidia"], "Nvidia"),
    (["马斯克", "馬斯克", "musk", "特斯拉", "tesla", "spacex", "starship"], "Elon Musk Tesla"),
    (["人工智能", "人工智慧", "artificialintelligence"], "AI"),
    # ── 歐洲 ──
    (["欧盟", "歐盟", "德国大选", "法国大选", "europeanunion"], "Europe election"),
    (["脱欧", "脫歐", "brexit", "英国首相", "britishpm"], "UK politics"),
    # ── 選舉泛詞（最後兜底，只用中文避免英文 selection 誤判）──
    (["大选", "大選", "选举", "選舉"], "election"),
]

# ── 排除模式：這些話題在 Polymarket 幾乎找不到對應市場 ─────────────────
EXCLUDE_PATTERNS: list[str] = [
    # 教育 / 考試（高考類噪音）
    "高考", "中考", "考研", "录取", "錄取", "作文", "试卷", "試卷",
    # 娛樂 / 八卦
    "八卦", "绯闻", "緋聞", "离婚", "離婚", "结婚", "結婚", "怀孕", "懷孕",
    "艺人", "藝人", "明星", "偶像", "综艺", "綜藝", "电视剧", "電視劇",
    "票房", "网红", "網紅", "演唱会", "演唱會", "粉丝", "粉絲",
    # 個股 / A股噪音（非 Polymarket 標的）
    "股份", "涨停", "漲停", "跌停", "回购", "回購", "停牌", "港股", "a股",
    "板块", "板塊", "财报", "財報", "业绩", "業績",
    # 即時體育比分（太快跟不上）
    "进球", "進球", "比分", "联赛", "聯賽", "球员", "球員",
    # 地方民生 / 災害
    "地铁", "地鐵", "高铁", "高鐵", "塌方", "火灾", "火災", "台风", "颱風",
    "暴雨", "车祸", "車禍",
    # 其他
    "食安", "医疗", "醫療", "感冒", "彩票",
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
