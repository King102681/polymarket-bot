"""對照 simulator pseudonym ↔ discovery proxy_wallet ↔ pseudonym。"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core  # noqa
from whale_copy import discovery

print("=== whales.json (discovery 視角) ===")
for w in discovery.load():
    print(f"  {w.proxy_wallet} → {w.pseudonym}")

print("\n=== trades_*.jsonl 中的 proxyWallet ↔ pseudonym 對照 ===")
for tf in sorted(Path("data/backtest").glob("trades_*.jsonl")):
    counter = Counter()
    for line in open(tf, encoding="utf-8"):
        t = json.loads(line)
        counter[(t.get("proxyWallet"), t.get("pseudonym"))] += 1
    print(f"\n  {tf.name}:")
    for (w, p), c in counter.most_common(5):
        print(f"    wallet={w}  pseudonym={p!r}  n={c}")
