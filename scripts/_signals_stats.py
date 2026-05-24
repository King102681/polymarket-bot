"""快速統計 signals.jsonl 內各鯨魚訊號分佈、類型分佈。"""
import json
from collections import Counter
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core  # noqa
from whale_copy.market_classifier import classify
from whale_copy import discovery

DATA = Path(__file__).resolve().parent.parent / "data"

whales = {w.proxy_wallet: w.pseudonym for w in discovery.load()}
print(f"認可鯨魚: {len(whales)} -> {list(whales.values())}")

signals = []
for line in open(DATA / "signals.jsonl", encoding="utf-8"):
    if line.strip():
        signals.append(json.loads(line))

print(f"\n總訊號: {len(signals)}")
print(f"認可鯨魚的訊號: {sum(1 for s in signals if s['whale_wallet'] in whales)}")

print(f"\n按鯨魚分布:")
by_whale = Counter(s["whale_pseudonym"] for s in signals)
for name, cnt in by_whale.most_common():
    in_pool = "✓" if name in whales.values() else " "
    print(f"  {in_pool} {name:24s}: {cnt}")

print(f"\n認可鯨魚的訊號類型分布:")
relevant = [s for s in signals if s["whale_wallet"] in whales]
cat_counter = Counter()
for s in relevant:
    cat = classify(s.get("market_slug"), s.get("market_title"))
    cat_counter[cat] += 1
for cat, cnt in cat_counter.most_common():
    print(f"  {cat:10s}: {cnt}")

print(f"\n認可鯨魚的訊號（金額 USDC）分布:")
sizes = [s["whale_price"] * s["whale_size"] for s in relevant]
if sizes:
    import statistics
    print(f"  n={len(sizes)} min=${min(sizes):.0f} max=${max(sizes):.0f} median=${statistics.median(sizes):.0f}")
    over_2000 = sum(1 for x in sizes if x >= 2000)
    print(f"  ≥ $2000: {over_2000}")

print(f"\n認可鯨魚的訊號 sample (前 10):")
for s in relevant[:10]:
    cat = classify(s.get("market_slug"), s.get("market_title"))
    usd = s["whale_price"] * s["whale_size"]
    print(f"  {s['whale_pseudonym']:14s} [{cat:8s}] {s['outcome']:3s} @ {s['whale_price']:.3f} = ${usd:>8,.0f}  {s['market_title'][:55]}")
