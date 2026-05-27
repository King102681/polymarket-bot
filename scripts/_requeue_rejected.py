"""一次性工具：把舊門檻（$2000）擋掉但新門檻（$500）可通過的訊號，
從 processed_signal_hashes.json 中移除，讓下次 pipeline 重新評估。
"""
import json
import re
import sys
from pathlib import Path

for s in (sys.stdout, sys.stderr):
    if hasattr(s, "reconfigure"):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass

BASE = Path(__file__).resolve().parent.parent / "data"
rejected_p = BASE / "rejected_signals.jsonl"
processed_p = BASE / "processed_signal_hashes.json"

rejected = [json.loads(l) for l in rejected_p.open(encoding="utf-8") if l.strip()]
processed = set(json.load(processed_p.open(encoding="utf-8")))

NEW_THRESHOLD = 500

to_requeue = []
for r in rejected:
    reason = r.get("reason", "")
    m = re.search(r"鯨魚單 \$([0-9]+)", reason)
    if m:
        size = int(m.group(1))
        if size >= NEW_THRESHOLD:
            to_requeue.append(r["signal_tx_hash"])

print(f"可重新評估（>= ${NEW_THRESHOLD} 被舊門檻擋）: {len(to_requeue)} 筆")

before = len(processed)
for h in to_requeue:
    processed.discard(h)
print(f"processed_signal_hashes: {before} → {len(processed)} (-{before - len(processed)})")

with open(processed_p, "w", encoding="utf-8") as f:
    json.dump(sorted(processed), f)
print("✅ 已更新 processed_signal_hashes.json")
print("   下次 GHA pipeline 跑時，這些訊號會用新 $500 門檻重新評估。")
