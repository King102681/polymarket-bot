"""一次性補抓：對 whales.json 中所有認可鯨魚，回看 N 小時的 BUY 訊號。

用於：
- 第一次切換鯨魚池（whales.json 換人）後補抓歷史訊號
- 驗證 signal_generator pipeline

預設 72h 回看、500 筆 trades 上限。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core  # noqa

from whale_copy import monitor


def main() -> None:
    hours = float(sys.argv[1]) if len(sys.argv) > 1 else 72.0
    print(f"⚡ 強制回看 {hours:.1f} 小時、每隻鯨魚拉最多 500 筆 trades")
    monitor.scan_once(
        initial_lookback_sec=int(hours * 3600),
        trades_limit=500,
        force_lookback=True,
    )


if __name__ == "__main__":
    main()
