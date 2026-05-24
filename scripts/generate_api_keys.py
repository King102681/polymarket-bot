"""向 Polymarket CLOB 申請 API 憑證並追加到 ~/.polymarket/.env。

只在 POLY_API_KEY 失效或從未申請時執行。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from py_clob_client.client import ClobClient

from core import config


def main() -> None:
    if config.POLY_API_KEY:
        answer = input(
            f"POLY_API_KEY 已存在 ({config.POLY_API_KEY[:6]}...)。"
            "確認重新申請並覆蓋？(yes/no) "
        ).strip().lower()
        if answer != "yes":
            print("取消")
            return

    print("🔐 向 Polymarket 申請 API 憑證...")
    client = ClobClient(
        host="https://clob.polymarket.com",
        chain_id=config.CHAIN_ID,
        key=config.WALLET_PRIVATE_KEY,
    )
    creds = client.create_or_derive_api_creds()

    with open(config.ENV_PATH, "a", encoding="utf-8") as f:
        f.write("\n# === Regenerated CLOB credentials ===\n")
        f.write(f"POLY_API_KEY={creds.api_key}\n")
        f.write(f"POLY_API_SECRET={creds.api_secret}\n")
        f.write(f"POLY_API_PASSPHRASE={creds.api_passphrase}\n")

    print(f"✅ 已追加到 {config.ENV_PATH}")
    print("⚠️  舊的 POLY_API_KEY 變數仍在檔案上方，請手動刪除或保留作為備份")


if __name__ == "__main__":
    main()
