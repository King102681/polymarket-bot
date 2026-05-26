"""Forward Dry-Run PnL 追蹤器。

讀取 data/pending_orders.jsonl（signal_generator 輸出的建議下單），
對每一筆用 CLOB API 查詢市場是否已結算，計算模擬 PnL。

邏輯與 backtest/simulator.py 一致：
  - 若市場已結算 (closed=True + winner 標記) → 計算 payout/fees/net_pnl
  - 若市場尚未結算 → 顯示為 open
  - 若找不到市場 → 顯示為 not_found

輸出：
  - 終端機報表（勝率/PnL/ROI）
  - data/forward_results.jsonl（追加），方便日後累積

⚠️ 需要網路連線（mobile hotspot 或 VPN）
"""
import json
import time
from pathlib import Path
from collections import defaultdict
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core  # noqa: F401  (安裝 DNS patch)

import requests

CLOB_BASE = "https://clob.polymarket.com"
_TIMEOUT = 15
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_PENDING_PATH = _DATA_DIR / "pending_orders.jsonl"
_FORWARD_PATH = _DATA_DIR / "forward_results.jsonl"

# 手續費（與 backtest/fees.py 一致）
MAKER_FEE = 0.0010   # 0.10%
TAKER_FEE = 0.0020   # 0.20%


def _fetch_market_clob(condition_id: str) -> dict | None:
    try:
        r = requests.get(f"{CLOB_BASE}/markets/{condition_id}", timeout=_TIMEOUT)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def _winning_outcome(market: dict) -> str | None:
    """回傳獲勝 outcome 名稱（或 None 如果未結算）。"""
    if not market.get("closed"):
        return None
    for tk in market.get("tokens", []) or []:
        if tk.get("winner") is True or float(tk.get("price") or 0) >= 0.99:
            return tk.get("outcome")
    return None


def _calc_fees(bet_usdc: float, entry_price: float, shares: float) -> float:
    """計算手續費（taker）。"""
    return round(bet_usdc * TAKER_FEE, 6)


def load_pending() -> list[dict]:
    if not _PENDING_PATH.exists():
        return []
    return [json.loads(l) for l in open(_PENDING_PATH, encoding="utf-8") if l.strip()]


def load_processed_hashes() -> set[str]:
    if not _FORWARD_PATH.exists():
        return set()
    processed = set()
    for l in open(_FORWARD_PATH, encoding="utf-8"):
        if l.strip():
            r = json.loads(l)
            processed.add(r["signal_tx_hash"])
    return processed


def evaluate_order(order: dict) -> dict:
    """用 CLOB 查市場狀態，計算模擬 PnL。"""
    condition_id = order["condition_id"]
    market = _fetch_market_clob(condition_id)

    result = {
        "signal_tx_hash": order["signal_tx_hash"],
        "whale_pseudonym": order["whale_pseudonym"],
        "market_title": order["market_title"],
        "market_category": order.get("market_category", "other"),
        "outcome": order["outcome"],
        "whale_price": order["whale_price"],
        "suggested_price": order["suggested_price"],
        "suggested_cost_usdc": order["suggested_cost_usdc"],
        "detected_at": order["detected_at"],
        "evaluated_at": int(time.time()),
        "status": "open",
        "winning_outcome": None,
        "correct": None,
        "payout": 0.0,
        "fees": 0.0,
        "net_pnl": 0.0,
    }

    if market is None:
        result["status"] = "not_found"
        return result

    winning_outcome = _winning_outcome(market)
    if winning_outcome is None:
        result["status"] = "open"
        return result

    # 市場已結算
    result["status"] = "resolved"
    result["winning_outcome"] = winning_outcome

    bet = order["suggested_cost_usdc"]
    price = order["suggested_price"]
    shares = round(bet / price, 4) if price > 0 else 0

    correct = order["outcome"].lower() == winning_outcome.lower()
    result["correct"] = correct
    result["payout"] = round(shares, 4) if correct else 0.0
    result["fees"] = _calc_fees(bet, price, shares)
    result["net_pnl"] = round(result["payout"] - bet - result["fees"], 6)

    return result


def print_summary(results: list[dict], label: str) -> None:
    resolved = [r for r in results if r["status"] == "resolved"]
    open_ = [r for r in results if r["status"] == "open"]
    not_found = [r for r in results if r["status"] == "not_found"]

    print(f"\n  {label}")
    print(f"    總筆數: {len(results)}  已結算: {len(resolved)}  未結算: {len(open_)}  找不到: {len(not_found)}")

    if not resolved:
        print(f"    (尚無已結算訊號)")
        return

    wins = [r for r in resolved if r.get("correct")]
    pnls = [r["net_pnl"] for r in resolved]
    bets = [r["suggested_cost_usdc"] for r in resolved]
    avg_bet = sum(bets) / len(bets) if bets else 1
    roi = (sum(pnls) / len(pnls)) / avg_bet if avg_bet else 0

    print(f"    勝率    : {len(wins)}/{len(resolved)} = {len(wins)/len(resolved):.1%}")
    print(f"    總投入  : ${sum(bets):.2f}")
    print(f"    總 PnL  : ${sum(pnls):+.4f}")
    print(f"    avg PnL : ${sum(pnls)/len(pnls):+.4f} / 筆")
    print(f"    ROI     : {roi:+.2%}")


def main() -> None:
    orders = load_pending()
    print(f"📂 載入 {len(orders)} 筆 pending orders（data/pending_orders.jsonl）")

    if not orders:
        print("\n⚠️  pending_orders.jsonl 目前為空。")
        print("   GHA pipeline 還沒有產生通過過濾的訊號，或尚未執行。")
        print("   等 1-2 週 dry-run 累積後再跑此腳本。")
        print("\n   💡 提示：GHA 每 30 分鐘跑一次，目前 LIVE_MODE=false（dry-run 模式）。")
        print("   訊號出現條件：")
        print(f"     - 鯨魚買單 ≥ $2,000")
        print(f"     - 目前最佳 ask × 1.005 在 0.20-0.80 區間")
        print(f"     - 市場距結算 > 6 小時")
        print(f"     - 鯨魚不在黑名單")
        return

    # 已處理過的不重複查
    already_processed = load_processed_hashes()
    new_orders = [o for o in orders if o["signal_tx_hash"] not in already_processed]
    print(f"🔍 本次新評估: {len(new_orders)} 筆（已有 {len(already_processed)} 筆歷史記錄）")

    results: list[dict] = []

    # 先讀取歷史結果（已有的）
    if _FORWARD_PATH.exists():
        hist = [json.loads(l) for l in open(_FORWARD_PATH, encoding="utf-8") if l.strip()]
        results.extend(hist)
        print(f"   + 歷史結果 {len(hist)} 筆")

    # 評估新訂單
    if new_orders:
        print(f"\n⏳ 查詢 CLOB 市場狀態...")
        new_results = []
        for i, order in enumerate(new_orders, 1):
            title = order.get("market_title", "")[:40]
            r = evaluate_order(order)
            status_icon = {"resolved": "✅", "open": "⏳", "not_found": "❓"}.get(r["status"], "?")
            detail = ""
            if r["status"] == "resolved":
                detail = f"→ {'✓ 猜對' if r['correct'] else '✗ 猜錯'}  PnL=${r['net_pnl']:+.4f}"
            print(f"   [{i:2d}] {status_icon} {title:40s} {detail}")
            new_results.append(r)

        # 追加寫入
        _FORWARD_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_FORWARD_PATH, "a", encoding="utf-8") as f:
            for r in new_results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        results.extend(new_results)

    if not results:
        print("\n（無結果可顯示）")
        return

    # 匯總報表
    print(f"\n{'=' * 70}")
    print(f" 📊 Forward Dry-Run 累積成績")
    print(f"{'=' * 70}")

    print_summary(results, "全部")

    # 按時間分層（最近 7d / 7-14d / 14d+）
    now = int(time.time())
    w7 = [r for r in results if r["evaluated_at"] >= now - 7 * 86400]
    w14 = [r for r in results if now - 14 * 86400 <= r["evaluated_at"] < now - 7 * 86400]

    if w7:
        print_summary(w7, "最近 7 天")
    if w14:
        print_summary(w14, "7-14 天前")

    # 按鯨魚
    print(f"\n{'=' * 70}")
    print(f" 🐋 按鯨魚拆解（已結算）")
    print(f"{'=' * 70}")
    by_whale: dict[str, list] = defaultdict(list)
    for r in results:
        if r["status"] == "resolved":
            by_whale[r["whale_pseudonym"]].append(r)
    for name, items in by_whale.items():
        wins = sum(1 for r in items if r.get("correct"))
        pnls = [r["net_pnl"] for r in items]
        print(
            f"  {name[:22]:22s}  n={len(items):3d}  "
            f"win={wins}/{len(items)} ({wins/len(items):.0%})  "
            f"totalPnL=${sum(pnls):+8.4f}"
        )

    # 按 category
    print(f"\n{'=' * 70}")
    print(f" 📂 按類別拆解（已結算）")
    print(f"{'=' * 70}")
    by_cat: dict[str, list] = defaultdict(list)
    for r in results:
        if r["status"] == "resolved":
            by_cat[r["market_category"]].append(r)
    for cat, items in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
        wins = sum(1 for r in items if r.get("correct"))
        pnls = [r["net_pnl"] for r in items]
        print(
            f"  {cat:10s}  n={len(items):3d}  "
            f"win={wins}/{len(items)} ({wins/len(items):.0%})  "
            f"totalPnL=${sum(pnls):+8.4f}"
        )

    print(f"\n💾 結果已更新至 data/forward_results.jsonl")
    print(f"\n💡 提醒：需累積 N≥50 已結算訊號後，數字才有統計意義。")


if __name__ == "__main__":
    main()
