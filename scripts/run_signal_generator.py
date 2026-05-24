"""執行一次 signal_generator：把 signals.jsonl 中未處理的訊號轉成下單建議。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core  # noqa

from whale_copy import signal_generator


def main() -> None:
    orders, rejected = signal_generator.process_all()
    if orders:
        print("\n" + "=" * 100)
        print(" ✅ 通過的下單建議")
        print("=" * 100)
        for o in orders:
            print(
                f"  {o.whale_pseudonym:18s} [{o.market_category:8s}] "
                f"BUY {o.outcome[:4]:4s} @ {o.suggested_price:.3f} × {o.suggested_size:>6.2f} "
                f"= ${o.suggested_cost_usdc:>6.2f}"
            )
            print(f"     market: {o.market_title[:80]}")
            if o.notes:
                print(f"     notes : {o.notes}")
    if rejected:
        print("\n" + "=" * 100)
        print(f" ❌ 被拒絕的訊號（前 10 筆，共 {len(rejected)}）")
        print("=" * 100)
        from collections import Counter
        counter = Counter(r.reason.split(":")[0].split("<")[0].strip()[:40] for r in rejected)
        for reason, cnt in counter.most_common(10):
            print(f"  {cnt:4d}x  {reason}")


if __name__ == "__main__":
    main()
