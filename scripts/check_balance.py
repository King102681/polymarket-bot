"""查詢錢包 USDC / MATIC 餘額與相對初始本金的 PnL。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config
from core.polygon_client import PolygonClient


def main() -> None:
    poly = PolygonClient()
    usdc = poly.usdc_balance()
    matic = poly.matic_balance()
    profit = usdc - config.INITIAL_CAPITAL_USDC

    print("-" * 50)
    print(f"💼 錢包地址     : {poly.address}")
    print(f"💰 USDC 餘額    : {usdc:.2f}")
    print(f"⛽ MATIC 餘額   : {matic:.4f}")
    print(f"🏁 初始本金     : {config.INITIAL_CAPITAL_USDC:.2f}")
    sign = "+" if profit >= 0 else ""
    print(f"📊 PnL          : {sign}{profit:.2f} USDC")
    print("-" * 50)
    print("💡 提示：未結算部位的資金不會計入 USDC 餘額。")


if __name__ == "__main__":
    main()
