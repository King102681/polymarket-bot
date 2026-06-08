"""細分運動類型：soccer / tennis / baseball / basketball / hockey / other_sport / non_sport。

market_classifier.classify() 只能分到 "sports"；本模組進一步細分到具體運動，
供世界盃策略與足球專項回測使用。

判斷依據（由準到糙）：
  1. slug 前綴（最準，Polymarket slug 格式為 {聯賽碼}-{隊1}-{隊2}-{日期}-{盤口}）
  2. 足球獨有盤口指紋：-btts（兩隊都進球）、-draw（平局）→ 只有足球有
  3. title 關鍵詞兜底
"""
from __future__ import annotations

# ── slug 前綴 → 運動 ─────────────────────────────────────────────────────
# 足球：FIFA 系列用 startswith("fif") 抓全（fif / fifwc / fifwq / fifwcq …）
_SOCCER_PREFIXES = {
    # 主流洲際 / 俱樂部
    "uefa", "uel", "ucl", "concacaf", "conmebol", "copa", "euro",
    "afcon", "wcq", "epl", "mls", "soccer",
    # 西班牙
    "laliga", "es1", "es2", "es3",
    # 義大利（sea = Serie A，數據確認 Fiorentina/Atalanta）
    "sea", "se2", "it1", "it2", "seriea",
    # 法 / 德
    "fr1", "fr2", "ligue1", "de1", "de2", "bundesliga",
    # 日本
    "j1100", "j2100", "j3100", "j1", "j2", "j3",
    # 巴西 / 拉美
    "bra1", "bra2", "bra3", "arg1", "arg2", "mex1", "col1", "col2",
    # 中東 / 非洲
    "mar1", "mar2", "egy1", "egy2", "ksa", "tur1", "tur",
    # 其他歐洲
    "hr1", "ned", "por", "bel", "sco", "gre", "swi", "rus", "ukr",
    "den", "nor", "swe", "pol", "cze", "rou", "aut",
    # 亞太（chi = 中超，數據確認 Chengdu Rongcheng FC；aus = A-League）
    "chi", "aus", "kor", "ind", "tha", "vie",
}
_TENNIS_PREFIXES = {"atp", "wta", "itf", "challenger", "chal"}
_BASEBALL_PREFIXES = {"mlb", "kbo", "npb", "cpbl", "milb"}
_BASKETBALL_PREFIXES = {"nba", "wnba", "ncaab", "euroleague", "wcbk", "fibabk"}
_HOCKEY_PREFIXES = {"nhl", "ahl", "khl", "shl", "liiga"}

# 足球獨有盤口（前綴不認識時的兜底指紋）
_SOCCER_MARKET_FINGERPRINTS = ("-btts", "-draw")
_SOCCER_TITLE_FINGERPRINTS = ("both teams to score", "end in a draw", " fc ", " fc:")


def _prefix(slug: str) -> str:
    return slug.split("-", 1)[0] if slug else ""


def sport_type(slug: str | None, title: str | None) -> str:
    """回傳細分運動類型。非運動回傳 "non_sport"。"""
    s = (slug or "").lower()
    t = (title or "").lower()
    pre = _prefix(s)

    # FIFA 系列（國家隊 + 世界盃）一律足球
    if pre.startswith("fif"):
        return "soccer"
    # 籃球小聯賽前綴常為 bk*（bkfr1, bkligend, bkseriea …）
    if pre.startswith("bk"):
        return "basketball"

    if pre in _SOCCER_PREFIXES:
        return "soccer"
    if pre in _TENNIS_PREFIXES:
        return "tennis"
    if pre in _BASEBALL_PREFIXES:
        return "baseball"
    if pre in _BASKETBALL_PREFIXES:
        return "basketball"
    if pre in _HOCKEY_PREFIXES:
        return "hockey"

    # 足球盤口指紋（聯賽前綴不認識也能抓）
    if any(fp in s for fp in _SOCCER_MARKET_FINGERPRINTS):
        return "soccer"
    if any(fp in t for fp in _SOCCER_TITLE_FINGERPRINTS):
        return "soccer"

    # 棒球大小分常見 O/U 高分（8.5/10.5）但無法只靠 title 區分，留 other
    return "other_sport"


def is_soccer(slug: str | None, title: str | None) -> bool:
    return sport_type(slug, title) == "soccer"


def is_world_cup(slug: str | None, title: str | None) -> bool:
    """是否為世界盃（含正賽與資格賽）市場。"""
    s = (slug or "").lower()
    return s.startswith("fifwc") or s.startswith("fifwq") or s.startswith("fifwcq")
