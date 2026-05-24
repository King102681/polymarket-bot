"""執行鯨魚發現：抓 leaderboard、過濾、驗證、存 data/whales.json。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core  # noqa  # 觸發 DNS bypass 與 UTF-8

from whale_copy import discovery


def main() -> None:
    whales = discovery.discover()
    discovery.save(whales)
    print("\n" + "=" * 92)
    print(" 🐋 Top 鯨魚（按 30d ROI 降冪）")
    print("=" * 92)
    header = f"{'#':<3}{'pseudonym':<22}{'roi':>8}{'profit_30d':>14}{'volume_30d':>16}{'value_now':>14}{'7d':>5}"
    print(header)
    print("-" * 92)
    for i, w in enumerate(whales, 1):
        print(
            f"{i:<3}{w.pseudonym[:20]:<22}{w.roi_30d:>7.1%}"
            f"{w.profit_30d:>14,.0f}{w.volume_30d:>16,.0f}"
            f"{w.wallet_value_now:>14,.0f}{w.recent_trade_count_7d:>5}"
        )


if __name__ == "__main__":
    main()
