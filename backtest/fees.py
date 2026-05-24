"""Polymarket 手續費 + 滑點模型（保守估計）。

Polymarket 目前主打 0% trading fee，實際成本來源：
1. Bid-ask spread（滑點）：taker 永遠付 best ask，比 mid-price 高
2. Polygon gas：每筆 tx 約 0.005-0.05 MATIC
3. Redemption gas：結算後贖回 USDC 也要 gas

保守估計：進場 +0.5% 滑點，每 round trip $0.05 gas。
"""

DEFAULT_SLIPPAGE_RATIO = 0.005
DEFAULT_GAS_PER_ROUND_TRIP_USDC = 0.05
PROTOCOL_FEE_RATIO = 0.0


def entry_price_with_slippage(quoted_price: float, slippage: float = DEFAULT_SLIPPAGE_RATIO) -> float:
    """進場價：在報價（鯨魚 fill 或 best ask）基礎上加 slippage，capped to 0.999"""
    return min(quoted_price * (1 + slippage), 0.999)


def estimate_trade_cost(bet_usdc: float, gas: float = DEFAULT_GAS_PER_ROUND_TRIP_USDC) -> float:
    """單筆 round trip 的固定成本（gas + protocol fee）"""
    return gas + bet_usdc * PROTOCOL_FEE_RATIO
