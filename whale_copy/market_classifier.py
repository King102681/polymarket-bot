"""粗略判斷市場類型：sports / crypto / politics / other。

只用 trades endpoint 回傳的 slug + title，不需要額外查 Gamma /markets。
準確率約 85-95%，足以做鯨魚池過濾。
"""

_SPORTS_SLUG_PREFIXES = (
    # 美式
    "mlb-", "nba-", "nfl-", "nhl-", "ncaaf-", "ncaab-", "wnba-",
    # 歐式 / 國際足球
    "epl-", "ucl-", "uefa-", "fifa-", "concacaf-", "mls-", "la-liga-",
    "bundesliga-", "serie-a-", "ligue-1-", "soccer-", "champions-league-",
    # 網球（ATP/WTA 巡迴賽分站）
    "atp-", "wta-", "wimbledon-", "us-open-", "australian-open-",
    "french-open-", "roland-garros-", "geneva-open-", "hamburg-",
    "birmingham-", "eastbourne-", "halle-", "queens-", "nottingham-",
    # ITF / 挑戰賽（J2100, M25, W25 等）
    "itf-", "challenger-", "j2100-", "j3100-", "m15-", "m25-", "w15-", "w25-",
    # 格鬥 / 賽車 / 高爾夫 / 其他
    "ufc-", "mma-", "boxing-", "f1-", "nascar-", "indycar-", "motogp-",
    "pga-", "lpga-", "golf-", "ipl-", "cricket-", "olympics-", "ryder-cup-",
    # 區域聯盟
    "kbo-", "cpbl-", "npb-", "nrl-", "afl-", "rugby-",
    # 各國足球聯賽（win/loss 市場格式）
    "j2100-", "j1-", "j2-", "j3-", "k-league-", "csl-", "a-league-",
)

# ⚠️ 全部必須小寫——classify() 比對前會把 blob 轉小寫，混大寫的項目會
# 靜默永遠比對不到（2026-07-10 實測發現：Spread:/Wimbledon/US Open 等
# 過去從未真正生效，只靠巧合命中小寫的 " vs " 才勉強抓到部分球類對戰標題）。
_SPORTS_TITLE_HINTS = (
    " vs. ", " vs ", " v ",
    "spread:", "o/u ", "moneyline",
    # 「Will X win?」類球賽市場
    "roland garros", "wimbledon", "us open", "australian open", "french open",
    "birmingham", "eastbourne", "halle ", "queen's ", "itf ",
    " atp:", " wta:", " atp ", " wta ",
    "roland-garros",
    # 「Will X win the Y?」奪冠盤：Y 是知名體育賽事時全屬 sports（2026-07-10
    # 新增：Q96s3kwozynxpau 的世界盃奪冠盤全被誤判成 other，才發現這個缺口）
    "world cup", "olympics", "olympic games", "euro 2026", "copa america",
    "champions league", "super bowl", "stanley cup", "nba finals", "world series",
)

_CRYPTO_HINTS = (
    "bitcoin", "ethereum", " btc ", " eth ", "solana", "dogecoin",
    "crypto", "binance", "coinbase", "stablecoin",
)

_POLITICS_HINTS = (
    "trump", "biden", "harris", "vance", "election", "senate",
    "house seat", "potus", "putin", "zelensky", "macron", "starmer",
    "netanyahu", "xi jinping", "powell", "fed ", "fomc", "rate cut",
    "tariff", "shutdown", "speaker",
)

_TECH_AI_HINTS = (
    "openai", "anthropic", "gemini", " gpt", "claude", " ai ",
    "tesla", "musk", "apple", "google", "microsoft", "ipo",
)


def classify(slug: str | None, title: str | None) -> str:
    s = (slug or "").lower()
    t = (title or "").lower()
    blob = s + " || " + t

    if any(s.startswith(p) for p in _SPORTS_SLUG_PREFIXES):
        return "sports"
    if any(h in blob for h in _SPORTS_TITLE_HINTS):
        return "sports"
    if any(h in blob for h in _CRYPTO_HINTS):
        return "crypto"
    if any(h in blob for h in _POLITICS_HINTS):
        return "politics"
    if any(h in blob for h in _TECH_AI_HINTS):
        return "tech"
    return "other"


def is_sports(slug: str | None, title: str | None) -> bool:
    return classify(slug, title) == "sports"
