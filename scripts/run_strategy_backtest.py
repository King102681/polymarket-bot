"""套用 Day 6 學到的策略過濾，重跑樣本內外分析。

過濾規則（與 signal_generator 一致）：
1. 黑名單剔除 Countryside (pseudonym=Unique-Congressperson)
2. 進場價 0.20 ≤ entry_price ≤ 0.80（用 whale_price * 1.005 模擬實盤 best_ask）
3. 沿用原有的 MIN_WHALE_SIZE_USDC=2000、MIN_BET=1

對比「無策略過濾」與「有策略過濾」兩個版本的 IS/OOS。
"""
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core  # noqa

# 對齊 signal_generator 的設定
WHALE_BLACKLIST_PSEUDONYM = {"Unique-Congressperson"}
MIN_ENTRY_PRICE = 0.20
MAX_ENTRY_PRICE = 0.80

RESULTS_PATH = Path(__file__).resolve().parent.parent / "data" / "backtest" / "simulation_results.jsonl"


def load_results() -> list[dict]:
    return [json.loads(l) for l in open(RESULTS_PATH, encoding="utf-8") if l.strip()]


def apply_strategy_filter(r: dict) -> bool:
    """是否通過新策略過濾。預設要 passed_filter（原本門檻：whale_usdc >= $2000）"""
    if not r["passed_filter"]:
        return False
    if r["whale_pseudonym"] in WHALE_BLACKLIST_PSEUDONYM:
        return False
    # 用 entry_price 當實盤 best_ask 的 proxy
    if not (MIN_ENTRY_PRICE <= r["entry_price"] <= MAX_ENTRY_PRICE):
        return False
    return True


def summarize(items: list[dict], label: str) -> dict:
    resolved = [r for r in items if r["market_resolved"]]
    pnls = [r["net_pnl"] for r in resolved]
    bets = [r["bet_usdc"] for r in resolved]
    wins = [r for r in resolved if r["payout"] > 0]
    return {
        "label": label,
        "total": len(items),
        "resolved": len(resolved),
        "win_rate": len(wins) / len(resolved) if resolved else 0,
        "total_pnl": sum(pnls),
        "total_bet": sum(bets),
        "avg_pnl": statistics.mean(pnls) if pnls else 0,
        "median_pnl": statistics.median(pnls) if pnls else 0,
        "std_pnl": statistics.stdev(pnls) if len(pnls) > 1 else 0,
        "roi_per_trade": (statistics.mean(pnls) / (sum(bets) / len(bets))) if bets else 0,
    }


def print_summary(s: dict) -> None:
    print(f"\n  {s['label']}")
    print(f"    n / resolved          : {s['total']} / {s['resolved']}")
    if s['resolved'] == 0:
        print(f"    (無已結算資料)")
        return
    print(f"    勝率                  : {s['win_rate']:.1%}")
    print(f"    總投入                : ${s['total_bet']:.2f}")
    print(f"    總 PnL                : ${s['total_pnl']:+.2f}")
    print(f"    avg PnL / 筆           : ${s['avg_pnl']:+.4f}")
    print(f"    median PnL            : ${s['median_pnl']:+.4f}")
    print(f"    std (PnL)             : ${s['std_pnl']:.4f}")
    print(f"    ROI per trade         : {s['roi_per_trade']:+.2%}")


def compare(name: str, results: list[dict]) -> None:
    print(f"\n{'=' * 72}")
    print(f" {name}")
    print(f"{'=' * 72}")
    in_sample = [r for r in results if 30 < r["days_ago"] <= 90]
    out_sample = [r for r in results if r["days_ago"] <= 30]
    print_summary(summarize(results, "全部 (90d)"))
    print_summary(summarize(in_sample, "In-Sample (30-90d ago)"))
    print_summary(summarize(out_sample, "Out-of-Sample (last 30d)"))


def main() -> None:
    all_results = load_results()
    print(f"📊 載入 {len(all_results)} 筆模擬結果\n")

    # Baseline：原版過濾（只看 passed_filter）
    baseline = [r for r in all_results if r["passed_filter"]]
    compare("📌 BASELINE：原 signal_generator 過濾（whale_usdc≥$2000, 任何進場價, 任何鯨魚）", baseline)

    # Strategy：套用 Day 6 新策略
    strategy = [r for r in all_results if apply_strategy_filter(r)]
    compare(f"🎯 STRATEGY：黑名單 + entry [{MIN_ENTRY_PRICE}-{MAX_ENTRY_PRICE}]", strategy)

    # 兩者差異
    print(f"\n{'=' * 72}")
    print(f" 📈 策略影響：通過數量 vs 期望值")
    print(f"{'=' * 72}")
    print(f"  baseline 通過: {len(baseline)} 筆")
    print(f"  strategy 通過: {len(strategy)} 筆 ({len(strategy)/len(baseline):.0%} of baseline)")

    # 按鯨魚 + 進場價區間 拆解 strategy 結果
    print(f"\n{'=' * 72}")
    print(f" 🐋 STRATEGY 中各鯨魚的貢獻")
    print(f"{'=' * 72}")
    by_whale = defaultdict(list)
    for r in strategy:
        if r["market_resolved"]:
            by_whale[r["whale_pseudonym"]].append(r)
    for name, items in by_whale.items():
        pnls = [r["net_pnl"] for r in items]
        wins = sum(1 for r in items if r["payout"] > 0)
        in_s = sum(1 for r in items if 30 < r["days_ago"] <= 90)
        out_s = sum(1 for r in items if r["days_ago"] <= 30)
        print(
            f"  {name[:22]:22s}  n={len(items):3d}  IS/OOS={in_s}/{out_s}  "
            f"win={wins}/{len(items)} ({wins/len(items):.0%})  "
            f"totalPnL=${sum(pnls):+8.2f}"
        )

    # 按 category × IS/OOS 拆解（策略過濾後）
    print(f"\n{'=' * 72}")
    print(f" 📂 STRATEGY：類別 × IS/OOS 拆解")
    print(f"{'=' * 72}")
    print(f"  {'類別':^10s}  {'IS n':>5s}  {'IS 勝率':>7s}  {'IS PnL':>9s}  {'IS ROI':>7s}  │  {'OOS n':>5s}  {'OOS 勝率':>8s}  {'OOS PnL':>9s}  {'OOS ROI':>8s}")
    print(f"  {'-'*10}  {'-'*5}  {'-'*7}  {'-'*9}  {'-'*7}  {'│':^3s}  {'-'*5}  {'-'*8}  {'-'*9}  {'-'*8}")

    by_cat_is: dict[str, list] = defaultdict(list)
    by_cat_oos: dict[str, list] = defaultdict(list)
    for r in strategy:
        if not r["market_resolved"]:
            continue
        cat = r["market_category"]
        if 30 < r["days_ago"] <= 90:
            by_cat_is[cat].append(r)
        elif r["days_ago"] <= 30:
            by_cat_oos[cat].append(r)

    all_cats = sorted(set(list(by_cat_is.keys()) + list(by_cat_oos.keys())))
    for cat in all_cats:
        is_items = by_cat_is.get(cat, [])
        oos_items = by_cat_oos.get(cat, [])

        def cat_stats(items: list) -> str:
            if not items:
                return f"{'—':>5s}  {'—':>7s}  {'—':>9s}  {'—':>7s}"
            pnls = [r["net_pnl"] for r in items]
            wins = sum(1 for r in items if r["payout"] > 0)
            bets = [r["bet_usdc"] for r in items]
            roi = (statistics.mean(pnls) / (sum(bets)/len(bets))) if bets else 0
            return (
                f"{len(items):5d}  {wins/len(items):7.1%}  ${sum(pnls):+8.2f}  {roi:+7.2%}"
            )

        print(f"  {cat:^10s}  {cat_stats(is_items)}  │  {cat_stats(oos_items)}")

    # 按進場價區間 × IS/OOS（策略過濾後）
    print(f"\n{'=' * 72}")
    print(f" 💡 STRATEGY：進場價區間 × IS/OOS")
    print(f"{'=' * 72}")
    price_buckets = [
        ("0.20-0.35", 0.20, 0.35),
        ("0.35-0.50", 0.35, 0.50),
        ("0.50-0.65", 0.50, 0.65),
        ("0.65-0.80", 0.65, 0.80),
    ]
    print(f"  {'區間':^10s}  {'IS n':>5s}  {'IS ROI':>7s}  {'IS PnL':>9s}  │  {'OOS n':>5s}  {'OOS ROI':>8s}  {'OOS PnL':>9s}")
    print(f"  {'-'*10}  {'-'*5}  {'-'*7}  {'-'*9}  {'│':^3s}  {'-'*5}  {'-'*8}  {'-'*9}")
    for bname, lo, hi in price_buckets:
        is_items = [r for r in strategy if r["market_resolved"] and 30 < r["days_ago"] <= 90 and lo <= r["entry_price"] < hi]
        oos_items = [r for r in strategy if r["market_resolved"] and r["days_ago"] <= 30 and lo <= r["entry_price"] < hi]

        def price_stats(items: list) -> str:
            if not items:
                return f"{'—':>5s}  {'—':>7s}  {'—':>9s}"
            pnls = [r["net_pnl"] for r in items]
            bets = [r["bet_usdc"] for r in items]
            roi = (statistics.mean(pnls) / (sum(bets)/len(bets))) if bets else 0
            return f"{len(items):5d}  {roi:+7.2%}  ${sum(pnls):+8.2f}"

        print(f"  {bname:^10s}  {price_stats(is_items)}  │  {price_stats(oos_items)}")


if __name__ == "__main__":
    main()
