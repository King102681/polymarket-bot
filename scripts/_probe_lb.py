"""一次性 probe：找出 lb-api leaderboard 接受的所有 window 值與欄位。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import requests

import core  # noqa

WINDOWS = ["1d", "7d", "30d", "90d", "all", "week", "month", "year", "1w", "1m"]
KINDS = ["profit", "volume"]

for kind in KINDS:
    print(f"\n=== {kind} ===")
    for w in WINDOWS:
        r = requests.get(
            f"https://lb-api.polymarket.com/{kind}",
            params={"window": w, "limit": 2},
            timeout=10,
        )
        status = r.status_code
        if status == 200:
            data = r.json()
            if isinstance(data, list) and data:
                top = data[0]
                amt = top.get("amount", 0)
                pseudo = top.get("pseudonym", "")
                print(f"  window={w:6s} OK   top={pseudo!r} amount=${amt:,.0f}")
            else:
                print(f"  window={w:6s} OK   (empty)")
        else:
            print(f"  window={w:6s} {status} {r.text[:70]}")
