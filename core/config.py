"""統一從 ~/.polymarket/.env 載入所有配置。所有模組必須 from core import config。"""
import os
from pathlib import Path
from dotenv import load_dotenv

ENV_PATH = Path.home() / ".polymarket" / ".env"
if not ENV_PATH.exists():
    raise FileNotFoundError(
        f"找不到 .env 於 {ENV_PATH}，請確認金鑰已遷移到該位置"
    )
load_dotenv(dotenv_path=ENV_PATH, override=True)

WALLET_PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY")
POLYGON_RPC_URL = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")

POLY_API_KEY = os.getenv("POLY_API_KEY")
POLY_API_SECRET = os.getenv("POLY_API_SECRET")
POLY_API_PASSPHRASE = os.getenv("POLY_API_PASSPHRASE")

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

LIVE_MODE = os.getenv("LIVE_MODE", "false").lower() == "true"
MAX_BET_USDC = float(os.getenv("MAX_BET_USDC", "10"))
MAX_TOTAL_OPEN_USDC = float(os.getenv("MAX_TOTAL_OPEN_USDC", "100"))
DAILY_LOSS_LIMIT_USDC = float(os.getenv("DAILY_LOSS_LIMIT_USDC", "10"))
WHALE_FOLLOW_RATIO = float(os.getenv("WHALE_FOLLOW_RATIO", "0.001"))
INITIAL_CAPITAL_USDC = float(os.getenv("INITIAL_CAPITAL_USDC", "100"))

# ── 策略 B：TrendRadar × Claude 自主交易 ──────────────────────────────────
# headless 管線呼叫 Anthropic API 由 Claude 判斷情緒與下注（與鯨魚跟單獨立）。
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
# 配對/翻譯用便宜模型；下注判斷用較強模型。皆可用環境變數覆寫。
TREND_MATCHER_MODEL = os.getenv("TREND_MATCHER_MODEL", "claude-haiku-4-5")
TREND_EVALUATOR_MODEL = os.getenv("TREND_EVALUATOR_MODEL", "claude-opus-4-8")
# newsnow 平台（以財經/國際線為主——對應 Polymarket 政治/地緣/宏觀市場）
TREND_PLATFORMS = os.getenv(
    "TREND_PLATFORMS",
    # 財經快訊（宏觀·加密）+ 中文國際新聞（地緣·政治）+ 英文科技（AI·加密）
    # 刻意排除純國內噪音源（weibo/baidu/douyin/xueqiu/gelonghui → 高考·個股·娛樂）
    "wallstreetcn-hot,cls-hot,jin10,cankaoxiaoxi,zaobao,sputniknewscn,kaopu,toutiao,"
    "hackernews,github-trending-today,producthunt",
)
TREND_MIN_HEAT = float(os.getenv("TREND_MIN_HEAT", "40"))         # 熱度門檻（0-100）
TREND_MAX_PER_RUN = int(os.getenv("TREND_MAX_PER_RUN", "20"))     # 每輪最多評估幾個趨勢（規則式免費，可放寬）
TREND_MIN_CONFIDENCE = float(os.getenv("TREND_MIN_CONFIDENCE", "0.60"))
TREND_MIN_HOURS_LEFT = float(os.getenv("TREND_MIN_HOURS_LEFT", "48"))  # 距結算 < 48h 不下
TREND_MIN_ENTRY_PRICE = float(os.getenv("TREND_MIN_ENTRY_PRICE", "0.10"))
TREND_MAX_ENTRY_PRICE = float(os.getenv("TREND_MAX_ENTRY_PRICE", "0.90"))
TREND_EXTERNAL_ENABLED = os.getenv("TREND_EXTERNAL_ENABLED", "true").lower() == "true"  # 併入英文政治/地緣 RSS 源

USDC_ADDRESS = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
POLYMARKET_CTF_EXCHANGE = "0x4bFb9717357033D56508891DE7463f66f97dF2b6"
CHAIN_ID = 137


def validate() -> None:
    """檢查必要環境變數齊備，缺一即拋例外。程式啟動時呼叫一次。"""
    required = {
        "WALLET_PRIVATE_KEY": WALLET_PRIVATE_KEY,
        "POLY_API_KEY": POLY_API_KEY,
        "POLY_API_SECRET": POLY_API_SECRET,
        "POLY_API_PASSPHRASE": POLY_API_PASSPHRASE,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise ValueError(f"缺少必要環境變數: {missing}")


def validate_trend() -> None:
    """策略 B 額外需要 ANTHROPIC_API_KEY；下單部分仍沿用 validate() 的 Polymarket 金鑰。"""
    if not ANTHROPIC_API_KEY:
        raise ValueError(
            "缺少 ANTHROPIC_API_KEY——策略 B 需要它呼叫 Claude API。"
            "請加到 ~/.polymarket/.env"
        )
