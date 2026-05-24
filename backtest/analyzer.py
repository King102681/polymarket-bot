"""分析模擬結果：整體勝率/PnL、in-sample vs out-of-sample、按 category/whale 拆分。"""
import json
import statistics
from collections import defaultdict
from pathlib import Path

_BACKTEST_DIR = Path(__file__).resolve().parent.parent / "data" / "backtest"
_RESULTS_PATH = _BACKTEST_DIR / "simulation_results.jsonl"


def _load() -> list[dict]:
    if not _RESULTS_PATH.exists():
        return []
    return [json.loads(l) for l in open(_RESULTS_PATH, encoding="utf-8") if l.strip()]


def _slice_summary(results: list[dict], label: str) -> dict:
    passed = [r for r in results if r["passed_filter"]]
    resolved = [r for r in passed if r["market_resolved"]]
    pnls = [r["net_pnl"] for r in resolved]
    wins = [r for r in resolved if r["payout"] > 0]
    return {
        "label": label,
        "total_signals": len(results),
        "passed_filter": len(passed),
        "resolved": len(resolved),
        "open": len(passed) - len(resolved),
        "win_rate": len(wins) / len(resolved) if resolved else 0.0,
        "total_pnl": sum(pnls),
        "avg_pnl": statistics.mean(pnls) if pnls else 0.0,
        "median_pnl": statistics.median(pnls) if pnls else 0.0,
        "std_pnl": statistics.stdev(pnls) if len(pnls) > 1 else 0.0,
        "best": max(pnls) if pnls else 0.0,
        "worst": min(pnls) if pnls else 0.0,
        "total_bet": sum(r["bet_usdc"] for r in resolved),
        "total_payout": sum(r["payout"] for r in resolved),
        "total_fees": sum(r["fees"] for r in resolved),
    }


def _print(s: dict) -> None:
    print(f"\n{'=' * 72}")
    print(f" {s['label']}")
    print(f"{'=' * 72}")
    print(f"  訊號 / 通過 / 已結算 / 未結算    : {s['total_signals']} / {s['passed_filter']} / {s['resolved']} / {s['open']}")
    if s["resolved"] == 0:
        print(f"  （無已結算 trades 可分析）")
        return
    print(f"  勝率                              : {s['win_rate']:.1%}")
    print(f"  總投入 / 總回收 / 總費用 (USDC)    : ${s['total_bet']:.2f} / ${s['total_payout']:.2f} / ${s['total_fees']:.2f}")
    print(f"  總 PnL                            : ${s['total_pnl']:+.2f}")
    print(f"  avg PnL / 筆                      : ${s['avg_pnl']:+.4f}")
    print(f"  median PnL                        : ${s['median_pnl']:+.4f}")
    print(f"  std (PnL)                         : ${s['std_pnl']:.4f}")
    print(f"  best / worst                      : ${s['best']:+.2f} / ${s['worst']:+.2f}")
    avg_bet = s["total_bet"] / s["resolved"] if s["resolved"] else 0
    if avg_bet > 0:
        print(f"  ROI per trade                     : {s['avg_pnl']/avg_bet:+.2%}")


def analyze() -> None:
    results = _load()
    print(f"📊 載入 {len(results)} 筆模擬結果")

    _print(_slice_summary(results, "📌 全部 (90 days)"))

    in_sample = [r for r in results if 30 < r["days_ago"] <= 90]
    out_sample = [r for r in results if r["days_ago"] <= 30]
    _print(_slice_summary(in_sample, "🔬 In-Sample (60d, 30~90 天前)"))
    _print(_slice_summary(out_sample, "🎯 Out-of-Sample (30 天內)"))

    # 按 category
    print(f"\n{'=' * 72}")
    print(f" 📂 按 category（passed_filter + resolved）")
    print(f"{'=' * 72}")
    by_cat: dict[str, list] = defaultdict(list)
    for r in results:
        if r["passed_filter"] and r["market_resolved"]:
            by_cat[r["market_category"]].append(r)
    for cat in sorted(by_cat, key=lambda k: -sum(r["net_pnl"] for r in by_cat[k])):
        items = by_cat[cat]
        wins = sum(1 for r in items if r["payout"] > 0)
        pnls = [r["net_pnl"] for r in items]
        print(
            f"  {cat:10s} n={len(items):3d}  win={wins}/{len(items)} ({wins/len(items):.0%})  "
            f"totalPnL=${sum(pnls):+9.2f}  avg=${statistics.mean(pnls):+.4f}"
        )

    # 按鯨魚
    print(f"\n{'=' * 72}")
    print(f" 🐋 按鯨魚（passed_filter + resolved）")
    print(f"{'=' * 72}")
    by_whale: dict[str, list] = defaultdict(list)
    for r in results:
        if r["passed_filter"] and r["market_resolved"]:
            by_whale[r["whale_pseudonym"]].append(r)
    for name, items in by_whale.items():
        wins = sum(1 for r in items if r["payout"] > 0)
        pnls = [r["net_pnl"] for r in items]
        print(
            f"  {name[:18]:18s} n={len(items):3d}  win={wins}/{len(items)} ({wins/len(items):.0%})  "
            f"totalPnL=${sum(pnls):+9.2f}"
        )

    # 鯨魚自身的「進場價分布」也算一下，看是不是大多進場時 price 已偏高
    print(f"\n{'=' * 72}")
    print(f" 💡 鯨魚進場價分布（passed_filter + resolved）")
    print(f"{'=' * 72}")
    buckets = {"≤0.20": 0, "0.20-0.50": 0, "0.50-0.80": 0, "0.80-0.95": 0, "0.95-0.99": 0, "≥0.99": 0}
    bucket_items: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        if not (r["passed_filter"] and r["market_resolved"]):
            continue
        p = r["whale_price"]
        if p <= 0.20: key = "≤0.20"
        elif p <= 0.50: key = "0.20-0.50"
        elif p <= 0.80: key = "0.50-0.80"
        elif p <= 0.95: key = "0.80-0.95"
        elif p < 0.99: key = "0.95-0.99"
        else: key = "≥0.99"
        buckets[key] += 1
        bucket_items[key].append(r)
    for key, cnt in buckets.items():
        items = bucket_items.get(key, [])
        if not items:
            print(f"  {key:10s} n={cnt:3d}")
            continue
        wins = sum(1 for r in items if r["payout"] > 0)   # win = outcome 正確 (payout > 0)
        pnls = [r["net_pnl"] for r in items]
        bets = [r["bet_usdc"] for r in items]
        avg_bet = sum(bets) / len(bets)
        roi = statistics.mean(pnls) / avg_bet if avg_bet else 0
        print(
            f"  {key:10s} n={cnt:3d}  win_rate={wins/len(items):.0%}  "
            f"totalPnL=${sum(pnls):+8.2f}  avg=${statistics.mean(pnls):+.4f}  ROI={roi:+.2%}"
        )
