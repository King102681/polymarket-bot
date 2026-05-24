"""一次性授權 USDC 給 Polymarket CTF Exchange 合約。

只在第一次使用或授權額度不足時執行。會送出真實鏈上交易並消耗 MATIC。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web3 import Web3

from core import config
from core.polygon_client import PolygonClient, USDC_ABI


def main() -> None:
    poly = PolygonClient()
    current_allowance = poly.usdc_allowance_for(config.POLYMARKET_CTF_EXCHANGE)
    print(f"目前已授權給 CTF Exchange: {current_allowance:.2f} USDC")
    if current_allowance >= 100000:
        print("✅ 授權額度已充足（≥ 100,000 USDC），無需重新授權")
        return

    answer = input("確認授權 1,000,000 USDC 給 CTF Exchange？(yes/no) ").strip().lower()
    if answer != "yes":
        print("取消")
        return

    w3 = Web3(Web3.HTTPProvider(config.POLYGON_RPC_URL))
    account = w3.eth.account.from_key(config.WALLET_PRIVATE_KEY)
    usdc = w3.eth.contract(
        address=w3.to_checksum_address(config.USDC_ADDRESS),
        abi=USDC_ABI,
    )
    spender = w3.to_checksum_address(config.POLYMARKET_CTF_EXCHANGE)
    amount = w3.to_wei(1_000_000, "mwei")  # USDC 是 6 decimals

    tx = usdc.functions.approve(spender, amount).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gasPrice": w3.eth.gas_price,
    })
    signed = w3.eth.account.sign_transaction(tx, private_key=config.WALLET_PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"✅ 交易已送出: {tx_hash.hex()}")
    print(f"   等待區塊確認後，再跑 check_config.py 驗證授權額度")


if __name__ == "__main__":
    main()
