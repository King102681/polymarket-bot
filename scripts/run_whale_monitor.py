"""執行一次鯨魚監控掃描。

建議用排程器每 10 分鐘呼叫，或在 PowerShell 起一個 loop：
    while ($true) { python -m scripts.run_whale_monitor; Start-Sleep 600 }
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core  # noqa

from whale_copy import monitor


def main() -> None:
    new_signals = monitor.scan_once()
    if not new_signals:
        return
    print("\n" + "=" * 90)
    print(" 本輪新訊號（最多顯示前 20 筆）")
    print("=" * 90)
    for s in new_signals[:20]:
        when = datetime.fromtimestamp(s.trade_ts).strftime("%m-%d %H:%M")
        title = s.market_title[:55]
        usd = s.whale_price * s.whale_size
        print(
            f"  [{when}] {s.whale_pseudonym[:16]:16s} "
            f"BUY {s.outcome:3s} @ {s.whale_price:.3f} × {s.whale_size:>9,.0f}  "
            f"≈ ${usd:>10,.0f}"
        )
        print(f"              {title}")
    if len(new_signals) > 20:
        print(f"  ... 還有 {len(new_signals) - 20} 筆")


if __name__ == "__main__":
    main()
