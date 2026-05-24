"""跑完整回測：拉資料 → 模擬 → 分析。

用法：
    python -m scripts.run_backtest          # 預設回看 90 天
    python -m scripts.run_backtest 30       # 回看 30 天
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core  # noqa

from backtest import analyzer, pull_historical, simulator


def main() -> None:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 90

    print("=" * 72)
    print(f" 🔬 Step 1/3：拉鯨魚過去 {days} 天 + 對應市場結算狀態")
    print("=" * 72)
    pull_historical.pull_all(lookback_days=days)

    print("\n" + "=" * 72)
    print(" 🔬 Step 2/3：逐筆模擬跟單 PnL")
    print("=" * 72)
    simulator.simulate_all()

    print("\n" + "=" * 72)
    print(" 🔬 Step 3/3：分析（整體 / in-sample / out-of-sample / category / whale）")
    print("=" * 72)
    analyzer.analyze()


if __name__ == "__main__":
    main()
