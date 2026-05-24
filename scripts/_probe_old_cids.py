"""比較 Gamma vs CLOB 對「老 condition_id」（trade 在 90 天前的）的查詢。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core  # noqa
import requests

trades_path = Path(__file__).resolve().parent.parent / "data" / "backtest" / "trades_newdogbeginning.jsonl"

# 把 trades 按時間排序，取最舊 5 個
trades = sorted(
    (json.loads(l) for l in open(trades_path, encoding="utf-8")),
    key=lambda t: int(t.get("timestamp", 0)),
)
oldest = trades[:5]
print(f"Oldest 5 trades:")
for t in oldest:
    import time
    ago = (time.time() - int(t["timestamp"])) / 86400
    print(f"  {ago:.0f}d ago  cid={t['conditionId'][:24]}...  {(t.get('title') or '')[:60]}")

for t in oldest:
    cid = t["conditionId"]
    print(f"\n{'=' * 80}")
    print(f" cid={cid[:30]}...  trade title: {(t.get('title') or '')[:55]}")
    print(f"{'=' * 80}")

    # Gamma 預設
    r = requests.get("https://gamma-api.polymarket.com/markets", params={"condition_ids": cid}, timeout=15)
    print(f"  [A] Gamma 預設       : items={len(r.json()) if r.status_code == 200 else r.status_code}")
    # Gamma + archived=true
    r = requests.get("https://gamma-api.polymarket.com/markets", params={"condition_ids": cid, "archived": "true"}, timeout=15)
    print(f"  [B] Gamma archived=t : items={len(r.json()) if r.status_code == 200 else r.status_code}")
    # CLOB direct
    r = requests.get(f"https://clob.polymarket.com/markets/{cid}", timeout=15)
    print(f"  [C] CLOB /markets/   : status={r.status_code}", end="")
    if r.status_code == 200:
        m = r.json()
        print(f"  active={m.get('active')} closed={m.get('closed')} archived={m.get('archived')}")
        print(f"        question: {(m.get('question') or '')[:60]}")
        if m.get("tokens"):
            for tk in m["tokens"]:
                print(f"        token outcome={tk.get('outcome')} price={tk.get('price')} winner={tk.get('winner')}")
    else:
        print()
