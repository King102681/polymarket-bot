"""多策略設定檔。

每個 StrategyConfig 獨立運行，產生各自的：
  - data/pending_orders_{name}.jsonl
  - data/rejected_{name}.jsonl
  - data/processed_{name}.json

目前三個策略：
  political    - 長期政治/地緣市場（Spirit of Ukraine 類型）
  sports_live  - swisstony 網球直播大單跟單
  open         - 低門檻開放探索（數據收集）
"""
from dataclasses import dataclass, field


@dataclass
class StrategyConfig:
    name: str                          # 檔名用（小寫+底線）
    display_name: str                  # Telegram 顯示名稱
    emoji: str                         # TG emoji
    whale_filter: list                 # 只跟這些 pseudonym，空 = 全部
    min_size_usdc: float               # 鯨魚單最小金額
    min_market_hours_left: float       # 距結算最少小時數（現在）
    min_entry_hours_remaining: float   # 鯨魚進場時市場至少剩多少小時
    min_price: float                   # entry price 下限
    max_price: float                   # entry price 上限
    allowed_categories: set            # 允許類別，空 = 全部
    enabled: bool = True               # 可關閉個別策略


STRATEGIES: dict[str, StrategyConfig] = {

    # ── 策略A：長期政治 / 地緣市場 ─────────────────────────────────────
    "political": StrategyConfig(
        name="political",
        display_name="政治/地緣市場",
        emoji="🗳️",
        whale_filter=[],               # 所有非黑名單鯨魚
        min_size_usdc=100.0,           # $100：抓 Spirit of Ukraine 小額試水單
        min_market_hours_left=6.0,
        min_entry_hours_remaining=168.0,  # 7 天以上才跟
        min_price=0.20,
        max_price=0.87,
        allowed_categories={"other"},  # 只跟政治/地緣
        enabled=True,
    ),

    # ── 策略B：swisstony 網球直播大單 ──────────────────────────────────
    "sports_live": StrategyConfig(
        name="sports_live",
        display_name="體育直播跟單",
        emoji="🎾",
        whale_filter=["swisstony"],    # 只跟 swisstony
        min_size_usdc=500.0,           # 只跟他的大單（$500+）
        min_market_hours_left=0.25,    # 至少還有 15 分鐘
        min_entry_hours_remaining=0.0, # 不限制進場時距（允許當日賽事）
        min_price=0.70,                # 他通常在 0.75-0.97 進場
        max_price=0.97,
        allowed_categories={"sports"},
        enabled=True,
    ),

    # ── 策略C：開放探索（低門檻，收集數據）────────────────────────────
    "open": StrategyConfig(
        name="open",
        display_name="開放探索",
        emoji="🔍",
        whale_filter=[],               # 所有鯨魚
        min_size_usdc=50.0,            # $50 以上
        min_market_hours_left=1.0,     # 至少 1 小時
        min_entry_hours_remaining=0.0, # 不限
        min_price=0.15,
        max_price=0.95,
        allowed_categories=set(),      # 所有類別
        enabled=True,
    ),
}
