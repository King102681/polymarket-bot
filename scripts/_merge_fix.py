"""一次性：從遠端版本的 processed_signal_hashes.json 合併，
並移除需要重新評估的 33 個 hash。"""
import json
import re
import subprocess
import sys
from pathlib import Path

for s in (sys.stdout, sys.stderr):
    if hasattr(s, "reconfigure"):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass

BASE = Path(__file__).resolve().parent.parent / "data"

# 1. 取得遠端最新版本的 processed hashes
result = subprocess.run(
    ["git", "show", "origin/main:data/processed_signal_hashes.json"],
    capture_output=True, text=True, encoding="utf-8",
    cwd=str(Path(__file__).resolve().parent.parent)
)
remote_hashes = set(json.loads(result.stdout))
print(f"遠端 processed hashes: {len(remote_hashes)}")

# 2. 找出「因 $2000 門檻被拒、但 >= $500 應重評」的 hash
rejected_p = BASE / "rejected_signals.jsonl"
rejected = [json.loads(l) for l in rejected_p.open(encoding="utf-8") if l.strip()]

to_requeue = []
for r in rejected:
    reason = r.get("reason", "")
    m = re.search(r"鯨魚單 \$([0-9]+)", reason)
    if m and int(m.group(1)) >= 500:
        to_requeue.append(r["signal_tx_hash"])

print(f"需要重新評估的 hash: {len(to_requeue)}")

# 3. 從遠端版本移除這些 hash
before = len(remote_hashes)
for h in to_requeue:
    remote_hashes.discard(h)
removed = before - len(remote_hashes)
print(f"實際移除: {removed} 筆（其餘在遠端新 hash 中不存在）")
print(f"最終 hash 數: {len(remote_hashes)}")

# 4. 寫入本地
p = BASE / "processed_signal_hashes.json"
with open(p, "w", encoding="utf-8") as f:
    json.dump(sorted(remote_hashes), f)
print(f"✅ 已寫入 {p}")
