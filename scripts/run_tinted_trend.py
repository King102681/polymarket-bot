"""Tinted-Consciousness 時間趨勢分析。

目的：驗證 OOS-IS 差距是否源自鯨魚「策略隨時間進化」（而非純選擇偏差）。

分析邏輯：
  - 只看通過 Day 6 策略過濾（entry 0.20-0.80 + 非黑名單）的 Tinted-Consciousness 交易
  - 按 10 天滾動視窗分解 PnL / 勝率
  - 若越近期表現越好 → 兼有「鯨魚進化 + 選擇偏差」雙重因素
  - 若表現無規律 → 純隨機取樣偏差，OOS 的 +35% 不可複製

此分析不需要 API，純讀 data/backtest/simulation_results.jsonl。
"""
import json
import statistics
from collections import defaultdict
from pathlib import Path
import sys

# ── stdout UTF-8（Windows 終端機避免 emoji crash）─────────────────────────────
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:
            pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RESULTS_PATH = Path(__file__).resolve().parent.parent / "data" / "backtest" / "simulation_results.jsonl"

MIN_ENTRY_PRICE = 0.20
MAX_ENTRY_PRICE = 0.80
BLACKLIST_PSEUDONYM = {"Unique-Congressperson"}


def load() -> list[dict]:
    return [json.loads(l) for l in open(RESULTS_PATH, encoding="utf-8") if l.strip()]


def strategy_filter(r: dict) -> bool:
    if not r["passed_filter"]:
        return False
    if r["whale_pseudonym"] in BLACKLIST_PSEUDONYM:
        return False
    if not (MIN_ENTRY_PRICE <= r["entry_price"] <= MAX_ENTRY_PRICE):
        return False
    return True


def print_bar(val: float, scale: float = 1.0, width: int = 20) -> str:
    """把 PnL 數值轉成簡單文字 bar。"""
    normalized = val / scale if scale else 0
    filled = min(int(abs(normalized) * width), width)
    if val >= 0:
        return "+" + "█" * filled + " " * (width - filled)
    else:
        return "-" + "░" * filled + " " * (width - filled)


def main() -> None:
    all_r = load()
    print(f"📊 載入 {len(all_r)} 筆模擬結果")

    # 只保留 Tinted + strategy filter + resolved
    tinted = [r for r in all_r if strategy_filter(r) and r["market_resolved"]]
    print(f"🔬 Tinted-Consciousness 策略過濾後已結算: {len(tinted)} 筆")
    if not tinted:
        print("⚠️  無資料")
        return

    days_range = (min(r["days_ago"] for r in tinted), max(r["days_ago"] for r in tinted))
    print(f"   days_ago 範圍: {days_range[1]:.1f} ~ {days_range[0]:.1f} 天前")

    print(f"\n{'=' * 78}")
    print(f" 📅 10 天滾動視窗分解（越左邊越是 OOS，越右邊越是 IS 深處）")
    print(f"{'=' * 78}")
    print(f"  {'視窗':^12s}  {'n':>4s}  {'勝率':>6s}  {'totalPnL':>10s}  {'avgPnL':>8s}  {'ROI':>7s}  PnL bar")
    print(f"  {'-'*12}  {'-'*4}  {'-'*6}  {'-'*10}  {'-'*8}  {'-'*7}  {'-'*22}")

    # 按 10 天視窗分組
    windows: dict[int, list[dict]] = defaultdict(list)
    for r in tinted:
        w = int(r["days_ago"] // 10)
        windows[w].append(r)

    total_pnl_max = max(abs(sum(r["net_pnl"] for r in items)) for items in windows.values()) or 1.0

    # 從最近到最遠（左到右 = OOS 到 IS）
    cumulative_pnl = 0.0
    for w in sorted(windows.keys()):
        items = windows[w]
        pnls = [r["net_pnl"] for r in items]
        wins = sum(1 for r in items if r["payout"] > 0)
        total_pnl = sum(pnls)
        cumulative_pnl += total_pnl
        bets = [r["bet_usdc"] for r in items]
        avg_bet = sum(bets) / len(bets) if bets else 1
        roi = statistics.mean(pnls) / avg_bet if avg_bet else 0
        win_rate = wins / len(items)
        label = f"{w*10:.0f}-{(w+1)*10:.0f}d ago"
        bar = print_bar(total_pnl, total_pnl_max)
        print(
            f"  {label:^12s}  {len(items):4d}  {win_rate:6.1%}  "
            f"${total_pnl:+9.2f}  ${statistics.mean(pnls):+7.4f}  {roi:+7.2%}  {bar}"
        )

    print(f"\n  累計 PnL（全 {len(tinted)} 筆）: ${cumulative_pnl:+.2f}")

    # IS vs OOS 對比（用 30d 切割）
    print(f"\n{'=' * 78}")
    print(f" 📊 OOS (0-30d) vs IS (30+d) 直接對比")
    print(f"{'=' * 78}")

    oos = [r for r in tinted if r["days_ago"] <= 30]
    is_ = [r for r in tinted if r["days_ago"] > 30]

    for label, items in [("OOS (0-30d)", oos), ("IS  (30+d)", is_)]:
        if not items:
            print(f"  {label}: 無資料")
            continue
        pnls = [r["net_pnl"] for r in items]
        wins = sum(1 for r in items if r["payout"] > 0)
        bets = [r["bet_usdc"] for r in items]
        avg_bet = sum(bets) / len(bets) if bets else 1
        roi = statistics.mean(pnls) / avg_bet if avg_bet else 0
        print(f"\n  {label}")
        print(f"    n={len(items)}  勝率={wins/len(items):.1%}  totalPnL=${sum(pnls):+.2f}  ROI={roi:+.2%}")
        print(f"    avg PnL={statistics.mean(pnls):+.4f}  std={statistics.stdev(pnls) if len(pnls)>1 else 0:.4f}")

    # 類別拆解（策略過濾後）
    print(f"\n{'=' * 78}")
    print(f" 📂 類別拆解（策略過濾後 Tinted 全部）")
    print(f"{'=' * 78}")
    by_cat: dict[str, list] = defaultdict(list)
    for r in tinted:
        by_cat[r["market_category"]].append(r)
    for cat, items in sorted(by_cat.items(), key=lambda kv: -sum(r["net_pnl"] for r in kv[1])):
        pnls = [r["net_pnl"] for r in items]
        wins = sum(1 for r in items if r["payout"] > 0)
        oos_items = [r for r in items if r["days_ago"] <= 30]
        is_items = [r for r in items if r["days_ago"] > 30]
        oos_pnl = sum(r["net_pnl"] for r in oos_items)
        is_pnl = sum(r["net_pnl"] for r in is_items)
        print(
            f"  {cat:10s}  n={len(items):3d}  win={wins/len(items):.0%}  "
            f"totalPnL=${sum(pnls):+8.2f}  "
            f"OOS=${oos_pnl:+7.2f}(n={len(oos_items)})  IS=${is_pnl:+7.2f}(n={len(is_items)})"
        )

    # 分析結論
    oos_pnl = sum(r["net_pnl"] for r in oos)
    is_pnl = sum(r["net_pnl"] for r in is_)
    oos_wins = sum(1 for r in oos if r["payout"] > 0) / len(oos) if oos else 0
    is_wins = sum(1 for r in is_ if r["payout"] > 0) / len(is_) if is_ else 0

    print(f"\n{'=' * 78}")
    print(f" 💡 分析師結論")
    print(f"{'=' * 78}")
    gap_win = oos_wins - is_wins
    print(f"""
  勝率差距 (OOS - IS) : {gap_win:+.1%}
  PnL 差距            : OOS ${oos_pnl:+.2f} vs IS ${is_pnl:+.2f}

  解讀：
  {'✅ 有時間趨勢（鯨魚策略進化）' if gap_win > 0.10 else '⚠️  無明顯時間趨勢（偏向純隨機）'}
  - 如果 OOS 勝率比 IS 高出 >10% → 鯨魚本身近期較強（非純選擇偏差）
  - 但無論如何，OOS 樣本 n={len(oos)} 太小，正期望值結論不夠穩定
  - 建議：累積 forward dry-run 4-8 週後（N≥50 筆），再做相同分析
""")


if __name__ == "__main__":
    main()
