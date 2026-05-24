"""列出 .env 與所有配置（敏感欄位遮蔽）"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config


def _mask(s: str | None) -> str:
    if not s:
        return "❌ MISSING"
    return s[:4] + "***" + s[-4:] if len(s) > 8 else "***"


def main() -> None:
    print(f"📂 .env path   : {config.ENV_PATH}")
    print(f"📂 .env exists : {config.ENV_PATH.exists()}")
    print()
    print("--- Secrets ---")
    print(f"WALLET_PRIVATE_KEY  : {_mask(config.WALLET_PRIVATE_KEY)}")
    print(f"POLY_API_KEY        : {_mask(config.POLY_API_KEY)}")
    print(f"POLY_API_SECRET     : {_mask(config.POLY_API_SECRET)}")
    print(f"POLY_API_PASSPHRASE : {_mask(config.POLY_API_PASSPHRASE)}")
    print(f"TG_BOT_TOKEN        : {_mask(config.TG_BOT_TOKEN)}")
    print(f"TG_CHAT_ID          : {_mask(config.TG_CHAT_ID)}")
    print()
    print("--- Network ---")
    print(f"POLYGON_RPC_URL     : {config.POLYGON_RPC_URL}")
    print(f"CHAIN_ID            : {config.CHAIN_ID}")
    print()
    print("--- Risk controls ---")
    print(f"LIVE_MODE           : {config.LIVE_MODE}")
    print(f"MAX_BET_USDC        : {config.MAX_BET_USDC}")
    print(f"MAX_TOTAL_OPEN_USDC : {config.MAX_TOTAL_OPEN_USDC}")
    print(f"DAILY_LOSS_LIMIT    : {config.DAILY_LOSS_LIMIT_USDC}")
    print(f"WHALE_FOLLOW_RATIO  : {config.WHALE_FOLLOW_RATIO}")
    print(f"INITIAL_CAPITAL     : {config.INITIAL_CAPITAL_USDC}")
    print()
    try:
        config.validate()
        print("✅ 必要環境變數齊備")
    except ValueError as e:
        print(f"❌ {e}")


if __name__ == "__main__":
    main()
