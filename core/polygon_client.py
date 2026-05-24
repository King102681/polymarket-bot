"""Polygon 鏈上操作：餘額查詢、USDC 授權檢查與授權。不處理 Polymarket CLOB 邏輯。"""
import json
from typing import Optional

from web3 import Web3

from core import config

USDC_ABI = json.loads("""
[
    {"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},
    {"constant":true,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"},
    {"constant":false,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"success","type":"bool"}],"type":"function"},
    {"constant":true,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"type":"function"}
]
""")


class PolygonClient:
    def __init__(self) -> None:
        self._w3 = Web3(Web3.HTTPProvider(config.POLYGON_RPC_URL))
        self._account = self._w3.eth.account.from_key(config.WALLET_PRIVATE_KEY)
        self._usdc = self._w3.eth.contract(
            address=self._w3.to_checksum_address(config.USDC_ADDRESS),
            abi=USDC_ABI,
        )
        self._decimals: Optional[int] = None

    @property
    def address(self) -> str:
        return self._account.address

    def is_connected(self) -> bool:
        return self._w3.is_connected()

    def _usdc_decimals(self) -> int:
        if self._decimals is None:
            self._decimals = self._usdc.functions.decimals().call()
        return self._decimals

    def matic_balance(self) -> float:
        """回傳 MATIC 餘額（單位 ether）"""
        wei = self._w3.eth.get_balance(self._account.address)
        return float(self._w3.from_wei(wei, "ether"))

    def usdc_balance(self) -> float:
        """回傳 USDC 餘額（單位 USDC）"""
        raw = self._usdc.functions.balanceOf(self._account.address).call()
        return raw / (10 ** self._usdc_decimals())

    def usdc_allowance_for(self, spender: str) -> float:
        """查詢已授權給某 spender 的 USDC 額度"""
        raw = self._usdc.functions.allowance(
            self._account.address,
            self._w3.to_checksum_address(spender),
        ).call()
        return raw / (10 ** self._usdc_decimals())
