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
    # 網球
    "atp-", "wta-", "wimbledon-", "us-open-", "australian-open-",
    "french-open-", "roland-garros-", "geneva-open-", "hamburg-",
    # 格鬥 / 賽車 / 高爾夫 / 其他
    "ufc-", "mma-", "boxing-", "f1-", "nascar-", "indycar-", "motogp-",
    "pga-", "lpga-", "golf-", "ipl-", "cricket-", "olympics-", "ryder-cup-",
    # 區域聯盟
    "kbo-", "cpbl-", "npb-", "nrl-", "afl-", "rugby-",
)

_SPORTS_TITLE_HINTS = (
    " vs. ", " vs ", " v ", "Spread:", "O/U ", "Moneyline",
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
