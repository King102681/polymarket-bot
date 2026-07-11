"""Forward Dry-Run PnL 追蹤器（多策略版）。

讀取所有策略的 pending_orders_*.jsonl（核准訂單的永久記錄），
對每一筆用 CLOB API 查詢市場是否已結算，計算模擬 PnL。

2026-07-12 重寫，修三個致命問題：
  1. 舊版讀已棄用的 data/pending_orders.jsonl（多策略改版後永遠是空的）
  2. 舊版假設鯨魚欄位（signal_tx_hash/whale_pseudonym），趨勢訂單會 KeyError
  3. 舊版查過一次就進去重名單，「未結算」的單永遠不會被重查 →
     現在只有 resolved 是終態，open/not_found 每次都重查

輸出：
  - 終端機報表（總覽 / 按策略 / 按信心區間 / 按鯨魚）
  - data/forward_results.jsonl（追加寫入；彙總時取每筆訂單最新狀態）

判決標準（CLAUDE.md）：≥30 筆已結算 + 總 ROI ≥ +15% + 連續 4 週。

⚠️ 需要網路連線（mobile hotspot 或 VPN）
"""
import json
import time
from pathlib import Path
from collections import defaultdict
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core  # noqa: F401  (安裝 DNS patch + UTF-8)

import requests

CLOB_BASE = "https://clob.polymarket.com"
_TIMEOUT = 15
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_FORWARD_PATH = _DATA_DIR / "forward_results.jsonl"

# 各策略的核准訂單檔與其識別欄位（whale 系用 signal_tx_hash，trend 用 trend_id）
_SOURCES = [
    ("political",   "pending_orders_political.jsonl",   "signal_tx_hash"),
    ("sports_live", "pending_orders_sports_live.jsonl", "signal_tx_hash"),
    ("soccer",      "pending_orders_soccer.jsonl",      "signal_tx_hash"),
    ("open",        "pending_orders_open.jsonl",        "signal_tx_hash"),
    ("trend",       "pending_orders_trend.jsonl",       "trend_id"),
]

TAKER_FEE = 0.0020   # 0.20%（與 backtest/fees.py 一致）


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


def load_all_orders() -> list[dict]:
    """讀入全部策略的核准訂單，統一欄位為 order_id / label / strategy。"""
    orders: list[dict] = []
    for strategy, fname, id_field in _SOURCES:
        p = _DATA_DIR / fname
        if not p.exists():
            continue
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            oid = o.get(id_field)
            if not oid or not o.get("condition_id"):
                continue
            orders.append({
                "order_id": oid,
                "strategy": o.get("strategy", strategy),
                # whale 訂單顯示鯨魚名；trend 訂單顯示 trend 標題
                "label": o.get("whale_pseudonym") or o.get("trend_title", "")[:24] or "?",
                "market_title": o.get("market_title", ""),
                "market_category": o.get("market_category", "other"),
                "condition_id": o["condition_id"],
                "outcome": o.get("outcome", ""),
                "suggested_price": float(o.get("suggested_price", 0) or 0),
                "suggested_cost_usdc": float(o.get("suggested_cost_usdc", 0) or 0),
                "confidence": o.get("confidence"),   # 只有 trend 有；whale 為 None
                "detected_at": o.get("detected_at", 0),
            })
    return orders


def load_latest_results() -> dict[str, dict]:
    """讀歷史結果，每筆訂單只保留最新一筆（append-only 檔案，後蓋前）。"""
    latest: dict[str, dict] = {}
    if not _FORWARD_PATH.exists():
        return latest
    for line in open(_FORWARD_PATH, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        # 相容舊格式（signal_tx_hash 當 key）
        oid = r.get("order_id") or r.get("signal_tx_hash")
        if oid:
            r["order_id"] = oid
            latest[oid] = r
    return latest


def evaluate_order(order: dict) -> dict:
    """用 CLOB 查市場狀態，計算模擬 PnL。"""
    market = _fetch_market_clob(order["condition_id"])

    result = {
        **order,
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
        return result

    result["status"] = "resolved"
    result["winning_outcome"] = winning_outcome

    bet = order["suggested_cost_usdc"]
    price = order["suggested_price"]
    shares = round(bet / price, 4) if price > 0 else 0

    correct = order["outcome"].lower() == winning_outcome.lower()
    result["correct"] = correct
    result["payout"] = round(shares, 4) if correct else 0.0
    result["fees"] = round(bet * TAKER_FEE, 6)
    result["net_pnl"] = round(result["payout"] - bet - result["fees"], 6)
    return result


def print_summary(results: list[dict], label: str) -> None:
    resolved = [r for r in results if r["status"] == "resolved"]
    open_ = [r for r in results if r["status"] == "open"]
    not_found = [r for r in results if r["status"] == "not_found"]

    print(f"\n  {label}")
    print(f"    總筆數: {len(results)}  已結算: {len(resolved)}  未結算: {len(open_)}  找不到: {len(not_found)}")

    if not resolved:
        print("    (尚無已結算訂單)")
        return

    wins = [r for r in resolved if r.get("correct")]
    total_pnl = sum(r["net_pnl"] for r in resolved)
    total_bet = sum(r["suggested_cost_usdc"] for r in resolved)
    roi = total_pnl / total_bet if total_bet else 0.0

    print(f"    勝率    : {len(wins)}/{len(resolved)} = {len(wins)/len(resolved):.1%}")
    print(f"    總投入  : ${total_bet:.2f}")
    print(f"    總 PnL  : ${total_pnl:+.4f}")
    print(f"    ROI     : {roi:+.2%}   （判決標準：≥30 筆已結算且 ROI ≥ +15%）")


def _conf_band(c) -> str:
    if c is None:
        return "無(whale)"
    if c < 0.35:
        return "< 0.35"
    if c < 0.45:
        return "0.35-0.45"
    if c < 0.55:
        return "0.45-0.55"
    return "≥ 0.55"


def main() -> None:
    orders = load_all_orders()
    per_src = defaultdict(int)
    for o in orders:
        per_src[o["strategy"]] += 1
    src_desc = "  ".join(f"{k}={v}" for k, v in sorted(per_src.items())) or "無"
    print(f"📂 載入核准訂單 {len(orders)} 筆（{src_desc}）")

    if not orders:
        print("\n⚠️  所有策略的 pending_orders_*.jsonl 都是空的——還沒有訂單通過過濾。")
        print("   等 GHA 累積出核准訂單後再跑此腳本。")
        return

    latest = load_latest_results()
    # 只有 resolved 是終態；open / not_found / 沒查過的每次都重查
    to_check = [o for o in orders
                if latest.get(o["order_id"], {}).get("status") != "resolved"]
    print(f"🔍 本次查詢 {len(to_check)} 筆（已終結 {len(orders) - len(to_check)} 筆跳過）")

    if to_check:
        print("\n⏳ 查詢 CLOB 市場狀態...")
        new_results = []
        for i, order in enumerate(to_check, 1):
            r = evaluate_order(order)
            icon = {"resolved": "✅", "open": "⏳", "not_found": "❓"}.get(r["status"], "?")
            detail = ""
            if r["status"] == "resolved":
                detail = f"→ {'✓ 猜對' if r['correct'] else '✗ 猜錯'}  PnL=${r['net_pnl']:+.4f}"
            print(f"   [{i:3d}] {icon} [{r['strategy']:11s}] {r['market_title'][:38]:38s} {detail}")
            new_results.append(r)
            latest[r["order_id"]] = r

        _FORWARD_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_FORWARD_PATH, "a", encoding="utf-8") as f:
            for r in new_results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    results = list(latest.values())

    print(f"\n{'=' * 70}")
    print(" 📊 Forward Dry-Run 累積成績")
    print(f"{'=' * 70}")
    print_summary(results, "全部")

    # 按策略
    print(f"\n{'=' * 70}")
    print(" 🧩 按策略拆解")
    print(f"{'=' * 70}")
    by_strat: dict[str, list] = defaultdict(list)
    for r in results:
        by_strat[r.get("strategy", "?")].append(r)
    for name, items in sorted(by_strat.items()):
        print_summary(items, f"[{name}]")

    # trend 專屬：按信心區間（降門檻收樣本的整個目的就在這張表）
    trend_resolved = [r for r in results
                      if r.get("strategy") == "trend" and r["status"] == "resolved"]
    if trend_resolved:
        print(f"\n{'=' * 70}")
        print(" 🎯 trend 按信心區間拆解（決定 LIVE 門檻用）")
        print(f"{'=' * 70}")
        by_band: dict[str, list] = defaultdict(list)
        for r in trend_resolved:
            by_band[_conf_band(r.get("confidence"))].append(r)
        for band in ["< 0.35", "0.35-0.45", "0.45-0.55", "≥ 0.55"]:
            items = by_band.get(band, [])
            if not items:
                continue
            wins = sum(1 for r in items if r.get("correct"))
            pnl = sum(r["net_pnl"] for r in items)
            bet = sum(r["suggested_cost_usdc"] for r in items)
            avg_entry = sum(r["suggested_price"] for r in items) / len(items)
            print(f"  {band:10s}  n={len(items):3d}  win={wins}/{len(items)}"
                  f"  平均進場價={avg_entry:.2f}  PnL=${pnl:+.4f}"
                  f"  ROI={pnl/bet:+.1%}" if bet else "")

    # whale 系：按鯨魚
    whale_resolved = [r for r in results
                      if r.get("strategy") != "trend" and r["status"] == "resolved"]
    if whale_resolved:
        print(f"\n{'=' * 70}")
        print(" 🐋 whale 系按鯨魚拆解（已結算）")
        print(f"{'=' * 70}")
        by_whale: dict[str, list] = defaultdict(list)
        for r in whale_resolved:
            by_whale[r.get("label", "?")].append(r)
        for name, items in by_whale.items():
            wins = sum(1 for r in items if r.get("correct"))
            pnls = [r["net_pnl"] for r in items]
            print(f"  {name[:22]:22s}  n={len(items):3d}  "
                  f"win={wins}/{len(items)} ({wins/len(items):.0%})  "
                  f"totalPnL=${sum(pnls):+8.4f}")

    print("\n💾 結果已更新至 data/forward_results.jsonl")


if __name__ == "__main__":
    main()
