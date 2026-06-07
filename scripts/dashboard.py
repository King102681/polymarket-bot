"""快速查看三策略即時狀態。

用法：
    python -m scripts.dashboard
"""
import sys, json, time
from pathlib import Path
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).resolve().parent.parent / "data"

STRATEGIES = [
    ("🗳️", "political",   "政治/地緣"),
    ("🎾", "sports_live", "體育直播"),
    ("🔍", "open",        "開放探索"),
]

WHALE_NAMES = {
    "0x204f72f35326db932158cba6adff0b9a1da95e14": "swisstony",
    "0x0c0e270cf879583d6a0142fc817e05b768d0434e": "Spirit of Ukraine",
    "0xdf17f4a8dd01a4cfa6fc3da323a2baee5f8697d1": "Soft-Lantern",
}

def _load(path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]

def main():
    now = time.time()
    ts  = time.strftime("%Y-%m-%d %H:%M:%S")
    sigs = _load(BASE / "signals.jsonl")

    print(f"\n{'='*62}")
    print(f"  📊 Polymarket Bot 儀表板  {ts}")
    print(f"{'='*62}")

    # ── 鯨魚概況 ─────────────────────────────────────────────────────
    whales_path = BASE / "whales.json"
    if whales_path.exists():
        whales = json.loads(whales_path.read_text(encoding="utf-8"))
        print(f"\n🐋 監控鯨魚（{len(whales)} 條）")
        for w in whales:
            # 最近 7 天活躍度
            w7 = [s for s in sigs
                  if s.get("whale_wallet") == w["proxy_wallet"]
                  and s.get("detected_at", 0) > now - 7*86400]
            big7 = [s for s in w7
                    if float(s.get("whale_price",0))*float(s.get("whale_size",0)) >= 500]
            last_ts = max((s.get("detected_at",0) for s in w7), default=0)
            last_str = f"{(now-last_ts)/3600:.0f}h前" if last_ts else "無紀錄"
            print(f"   {w['pseudonym'][:28]:28s}  7d訊號={len(w7):4d}  大單={len(big7):3d}  最後={last_str}")

    # ── 三策略 ────────────────────────────────────────────────────────
    print(f"\n{'─'*62}")
    print(f"  策略名稱           pending  rejected  最近拒絕原因 (top3)")
    print(f"{'─'*62}")

    for emoji, name, label in STRATEGIES:
        pend = _load(BASE / f"pending_orders_{name}.jsonl")
        rej  = _load(BASE / f"rejected_{name}.jsonl")
        top  = Counter(r["reason"][:50] for r in rej).most_common(3)
        top_str = " | ".join(f"{c}x {r}" for r, c in top[:2])
        print(f"  {emoji} {label:8s}  {len(pend):5d}   {len(rej):6d}   {top_str[:55]}")

        # 最新 pending order
        if pend:
            o = pend[-1]
            age = (now - o.get("detected_at", now)) / 3600
            print(f"     ✅最新: {o['whale_pseudonym'][:15]} | {o['market_title'][:40]} @ {o['suggested_price']} ({age:.0f}h前)")

    # ── 最近大單（過去 24h，>= $500）──────────────────────────────────
    cutoff24 = now - 24*3600
    recent_big = [
        (float(s.get("whale_price",0))*float(s.get("whale_size",0)), s)
        for s in sigs
        if s.get("detected_at",0) > cutoff24
        and float(s.get("whale_price",0))*float(s.get("whale_size",0)) >= 500
    ]
    recent_big.sort(reverse=True)

    if recent_big:
        print(f"\n📡 過去 24h 大單（≥$500）共 {len(recent_big)} 筆")
        for usdc, s in recent_big[:6]:
            age = (now - s.get("detected_at",0))/3600
            print(f"   {s['whale_pseudonym'][:14]:14s}  ${usdc:8,.0f}  p={s['whale_price']:.3f}  {s['market_title'][:45]}")
    else:
        print(f"\n📡 過去 24h 無大單（≥$500）")

    # ── 訊號總覽 ─────────────────────────────────────────────────────
    total = len(sigs)
    last24h = len([s for s in sigs if s.get("detected_at",0) > cutoff24])
    state = json.loads((BASE/"monitor_state.json").read_text(encoding="utf-8"))
    last_run = state.get("last_run_ts", 0)
    print(f"\n📦 訊號庫: 共 {total} 筆  過去24h新增 {last24h} 筆  最後掃描 {(now-last_run)/60:.0f}分前")
    print(f"{'='*62}\n")


if __name__ == "__main__":
    main()
