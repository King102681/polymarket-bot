"""驗證 Data API trades/positions 是否接受 leaderboard 的 proxyWallet。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import requests

import core  # noqa

# 用剛剛 leaderboard 拿到的 wallet
test_wallet = "0x5bec79df9add70a3892041ab1a5516b60f53b215"  # Mosley1

print(f"=== Test wallet: {test_wallet} ===\n")

# trades
print("[trades]")
r = requests.get("https://data-api.polymarket.com/trades", params={"user": test_wallet, "limit": 3}, timeout=15)
print(f"  status={r.status_code}")
if r.status_code == 200:
    data = r.json()
    if isinstance(data, list) and data:
        print(f"  count={len(data)}, sample keys: {list(data[0].keys())}")
        print(f"  sample[0]: {json.dumps(data[0], indent=2)[:600]}")
    else:
        print(f"  data: {str(data)[:200]}")

# positions
print("\n[positions]")
r = requests.get("https://data-api.polymarket.com/positions", params={"user": test_wallet, "sizeThreshold": 0, "limit": 3}, timeout=15)
print(f"  status={r.status_code}")
if r.status_code == 200:
    data = r.json()
    if isinstance(data, list) and data:
        print(f"  count={len(data)}, sample keys: {list(data[0].keys())}")
        print(f"  sample[0]: {json.dumps(data[0], indent=2)[:600]}")
    else:
        print(f"  data: {str(data)[:200]}")

# value
print("\n[value]")
r = requests.get("https://data-api.polymarket.com/value", params={"user": test_wallet}, timeout=15)
print(f"  status={r.status_code}")
if r.status_code == 200:
    print(f"  data: {json.dumps(r.json(), indent=2)[:300]}")
