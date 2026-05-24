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
