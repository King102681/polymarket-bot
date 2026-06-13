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
    allowed_categories: set            # 允許類別（classify: other/sports/politics），空 = 全部
    enabled: bool = True               # 可關閉個別策略
    # ── 細分運動過濾（sport_classifier: soccer/tennis/...），空 = 不過濾 ──
    sport_filter: set = field(default_factory=set)
    # ── per-strategy 下注參數（0 = 沿用全域 config）──────────────────────
    follow_ratio: float = 0.0          # 跟單比例（鯨魚單 × 此值）
    max_bet_usdc: float = 0.0          # 單筆上限
    min_follow_usdc: float = 1.0       # 單筆最低（低於則跳過）
    stop_loss_pct: float = 0.0         # 止損閾值（0 = 不啟用；0.15 = 跌破進場價85%賣出）


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
        # "other" = 地緣/宏觀兜底類；"politics" = 選舉類
        # classify() 對部分市場回傳 "politics"（如加州初選），這裡都收
        allowed_categories={"other", "politics"},
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
        # whale_filter 已鎖定 swisstony（體育專門戶），category 冗餘且誤殺
        # classify() 對 "Will X win?" 格式球賽判為 "other" → 23% 大單被誤過濾
        allowed_categories=set(),      # 不做類別過濾，讓 price + size + market 把關
        enabled=True,
    ),

    # ── 策略D：世界盃 / 足球狙擊（實盤候選，小注 + 止損）────────────────
    # 回測依據：beachboy4 edge+21%、RN1 大單 edge+11.8%、swisstony 足球 edge+6~9%
    # 關鍵：避開超熱門(>0.80，賠率太差)，鎖定甜區 0.55-0.80
    "soccer": StrategyConfig(
        name="soccer",
        display_name="世界盃足球狙擊",
        emoji="⚽",
        whale_filter=["beachboy4", "RN1", "swisstony"],  # 三隻足球鯨魚
        min_size_usdc=100.0,           # 世界盃期間降低：$100+ 就跟（RN1 大單 edge+11.8%）
        min_market_hours_left=0.5,
        min_entry_hours_remaining=0.0, # 允許賽前/當日盤
        min_price=0.55,                # ↓ 避開超熱門：甜區下限
        max_price=0.80,                # ↑ 避開超熱門：賠率太差不跟
        allowed_categories=set(),      # 類別不過濾，改用 sport_filter
        sport_filter={"soccer"},       # 只跟足球（濾掉 swisstony 的棒球/網球）
        follow_ratio=0.004,            # 鯨魚$250→跟$1, $750→$3(觸頂)
        max_bet_usdc=3.0,              # 單筆上限 $3（小注）
        min_follow_usdc=0.4,           # 最低 $0.4（$100 鯨魚單可觸發）
        stop_loss_pct=0.20,            # 跌破進場價 80% 止損（待止損模組實作）
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
