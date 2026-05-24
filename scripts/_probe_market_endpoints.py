"""比較 Gamma vs CLOB 對 condition_id 查詢的回應差異，特別是已結算市場。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core  # noqa
import requests

# 從 trades 拿一些 sample condition_ids
trades_path = Path(__file__).resolve().parent.parent / "data" / "backtest" / "trades_newdogbeginning.jsonl"
cids = []
for line in open(trades_path, encoding="utf-8"):
    t = json.loads(line)
    if t.get("conditionId") and t["conditionId"] not in cids:
        cids.append(t["conditionId"])
    if len(cids) >= 5:
        break

print(f"Sample condition_ids ({len(cids)}):")
for c in cids:
    print(f"  {c}")

for cid in cids[:3]:
    print(f"\n{'=' * 80}\n condition_id: {cid}\n{'=' * 80}")

    # 1. Gamma /markets 預設
    r = requests.get("https://gamma-api.polymarket.com/markets", params={"condition_ids": cid}, timeout=15)
    print(f"\n[A] Gamma /markets?condition_ids={cid[:20]}...")
    print(f"    status={r.status_code}, returned {len(r.json()) if r.status_code == 200 else '?'} items")

    # 2. Gamma + closed=true
    r = requests.get("https://gamma-api.polymarket.com/markets", params={"condition_ids": cid, "closed": "true"}, timeout=15)
    print(f"\n[B] Gamma + closed=true")
    print(f"    status={r.status_code}, returned {len(r.json()) if r.status_code == 200 else '?'} items")

    # 3. Gamma + active=false (allow inactive)
    r = requests.get("https://gamma-api.polymarket.com/markets", params={"condition_ids": cid, "active": "false"}, timeout=15)
    print(f"\n[C] Gamma + active=false")
    print(f"    status={r.status_code}, returned {len(r.json()) if r.status_code == 200 else '?'} items")

    # 4. CLOB markets/{cid}
    r = requests.get(f"https://clob.polymarket.com/markets/{cid}", timeout=15)
    print(f"\n[D] CLOB /markets/{cid[:20]}...")
    print(f"    status={r.status_code}")
    if r.status_code == 200:
        m = r.json()
        print(f"    keys: {list(m.keys())[:15]}")
        print(f"    active={m.get('active')} closed={m.get('closed')} accepting_orders={m.get('accepting_orders')}")
        print(f"    question: {(m.get('question') or '')[:60]}")
        if m.get("tokens"):
            for tk in m["tokens"]:
                print(f"      token: outcome={tk.get('outcome')} price={tk.get('price')} winner={tk.get('winner')}")
