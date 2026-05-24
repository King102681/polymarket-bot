"""檢查 entry_price ≥ 0.99 區間 simulation 結果是否合理。"""
import json
import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core  # noqa  triggers UTF-8 setup

p = Path(__file__).resolve().parent.parent / "data" / "backtest" / "simulation_results.jsonl"
hi = []
for line in open(p, encoding="utf-8"):
    r = json.loads(line)
    if r["passed_filter"] and r["market_resolved"] and r["entry_price"] >= 0.99:
        hi.append(r)

print(f"≥0.99 entry trades: {len(hi)}")
wins = [r for r in hi if r["payout"] > 0]
losses = [r for r in hi if r["payout"] == 0]
print(f"  wins: {len(wins)}  losses: {len(losses)}")
print(f"  total bet: ${sum(r['bet_usdc'] for r in hi):.2f}")
print(f"  total payout: ${sum(r['payout'] for r in hi):.2f}")
print(f"  total fees: ${sum(r['fees'] for r in hi):.2f}")
print(f"  total PnL: ${sum(r['net_pnl'] for r in hi):+.2f}")
print()
print(f"  bet distribution: {Counter(round(r['bet_usdc'],2) for r in hi).most_common(5)}")
print(f"  shares distribution sample: {sorted({round(r['shares'],2) for r in hi})[:5]} ... {sorted({round(r['shares'],2) for r in hi})[-5:]}")
print()
print("Sample of losses (which should each be ~-bet but might not be):")
for r in losses[:5]:
    print(f"  bet=${r['bet_usdc']:.2f}  entry={r['entry_price']:.4f}  shares={r['shares']:.4f}  "
          f"payout=${r['payout']:.4f}  fees=${r['fees']:.4f}  net=${r['net_pnl']:+.4f}")
    print(f"    market: {r['market_title'][:60]}")
    print(f"    outcome={r['outcome']!r}, win_idx={r['winning_outcome_index']}")
