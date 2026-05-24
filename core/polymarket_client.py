"""Polymarket CLOB / Gamma / Data API 封裝。

Day 1 階段只實作讀取功能（訂單簿、事件清單、鯨魚部位）。
寫入功能（下單）會在 Day 3 階段加入，且預設受 config.LIVE_MODE 控制。
"""
from typing import Any, Optional

import requests

from core import config

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
DATA_BASE = "https://data-api.polymarket.com"

_TIMEOUT = 10


class PolymarketClient:
    """Gamma + Data API 用 requests（無需認證、無 SSL 依賴）。
    CLOB 用 py-clob-client，採 lazy load，僅在 get_orderbook 等需要時才建構。
    """

    def __init__(self) -> None:
        self._clob: Optional[Any] = None

    def _get_clob(self) -> Any:
        if self._clob is None:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds

            self._clob = ClobClient(
                host=CLOB_BASE,
                key=config.WALLET_PRIVATE_KEY,
                chain_id=config.CHAIN_ID,
            )
            self._clob.set_api_creds(ApiCreds(
                api_key=config.POLY_API_KEY,
                api_secret=config.POLY_API_SECRET,
                api_passphrase=config.POLY_API_PASSPHRASE,
            ))
        return self._clob

    def list_active_events(self, limit: int = 20) -> list[dict[str, Any]]:
        """從 Gamma API 拉活躍事件（按交易量排序）"""
        url = f"{GAMMA_BASE}/events"
        params = {"limit": limit, "active": "true", "closed": "false", "sortBy": "volume"}
        r = requests.get(url, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()

    def list_top_markets(self, limit: int = 20) -> list[dict[str, Any]]:
        """Gamma /markets：按 24h 交易量排序拿真正在交易的市場（enableOrderBook=True）"""
        url = f"{GAMMA_BASE}/markets"
        params = {
            "active": "true",
            "closed": "false",
            "order": "volume24hr",
            "ascending": "false",
            "limit": limit,
        }
        r = requests.get(url, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()

    def get_orderbook(self, token_id: str) -> Any:
        """拿訂單簿（真實可成交價，非 mid-price）"""
        return self._get_clob().get_order_book(token_id)

    def get_user_positions(self, address: str) -> list[dict[str, Any]]:
        """Data API：某錢包目前部位。鯨魚追蹤核心。"""
        url = f"{DATA_BASE}/positions"
        params = {"user": address, "sizeThreshold": 0}
        r = requests.get(url, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()

    def get_user_trades(self, address: str, limit: int = 100) -> list[dict[str, Any]]:
        """Data API：某錢包交易歷史"""
        url = f"{DATA_BASE}/trades"
        params = {"user": address, "limit": limit}
        r = requests.get(url, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()

    def get_user_value(self, address: str) -> dict[str, Any]:
        """Data API：某錢包當前總價值（用於鯨魚資金門檻篩選）"""
        url = f"{DATA_BASE}/value"
        params = {"user": address}
        r = requests.get(url, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
