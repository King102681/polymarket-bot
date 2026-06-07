"""策略 B dry-run 下單執行器（與鯨魚策略獨立檔案）。

讀入 signal_evaluator 產生的 TrendOrder，dry-run 記錄到
data/executed_orders_trend.jsonl；LIVE_MODE=true 時送真實限價單
（沿用 whale_copy.executor._place_order_live，下單邏輯單一來源避免分歧）。

安全限制：MAX_TOTAL_OPEN_USDC（累計已送出但未結算的金額上限）。
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from core import config
from whale_copy.executor import _place_order_live  # 重用 live 下單邏輯（單一來源）

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_EXECUTED_PATH = _DATA_DIR / "executed_orders_trend.jsonl"
_EXEC_HASHES_PATH = _DATA_DIR / "executed_trend_hashes.json"


@dataclass
class TrendExecResult:
    trend_id: str
    condition_id: str
    executed_at: int
    trend_title: str
    market_title: str
    asset: str
    outcome: str
    suggested_price: float
    suggested_size: float
    cost_usdc: float
    confidence: float
    mode: str             # live | dry-run
    status: str           # submitted | dry-run | skipped | error
    order_id: str
    error: str
    reasoning: str


def _load_hashes() -> set[str]:
    if not _EXEC_HASHES_PATH.exists():
        return set()
    try:
        return set(json.loads(_EXEC_HASHES_PATH.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _save_hashes(h: set[str]) -> None:
    _EXEC_HASHES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _EXEC_HASHES_PATH.write_text(json.dumps(sorted(h)), encoding="utf-8")


def _append(results: list[TrendExecResult]) -> None:
    if not results:
        return
    _EXECUTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_EXECUTED_PATH, "a", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")


def _total_open_usdc() -> float:
    if not _EXECUTED_PATH.exists():
        return 0.0
    total = 0.0
    for line in open(_EXECUTED_PATH, encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            if r.get("status") in ("submitted", "dry-run"):
                total += r.get("cost_usdc", 0)
    return total


def execute_all(orders: list) -> list[TrendExecResult]:
    raw = [asdict(o) if hasattr(o, "__dataclass_fields__") else o for o in orders]
    done = _load_hashes()
    to_exec = [o for o in raw if f"{o['trend_id']}:{o['condition_id']}" not in done]
    if not to_exec:
        print("⚙️  trend executor: 無新訂單")
        return []

    mode = "live" if config.LIVE_MODE else "dry-run"
    open_usdc = _total_open_usdc()
    print(f"\n⚙️  trend executor [{mode.upper()}]: {len(to_exec)} 筆，目前開倉 ${open_usdc:.2f}")

    results: list[TrendExecResult] = []
    for o in to_exec:
        key = f"{o['trend_id']}:{o['condition_id']}"
        cost = float(o.get("suggested_cost_usdc", 0))
        title = str(o.get("market_title", ""))[:50]
        base = dict(
            trend_id=o["trend_id"], condition_id=o["condition_id"],
            executed_at=int(time.time()), trend_title=o.get("trend_title", ""),
            market_title=title, asset=o.get("asset", ""), outcome=o.get("outcome", ""),
            suggested_price=float(o.get("suggested_price", 0)),
            suggested_size=float(o.get("suggested_size", 0)), cost_usdc=cost,
            confidence=float(o.get("confidence", 0)), reasoning=o.get("reasoning", ""),
        )

        # ── 風險限制：總開倉上限 ──────────────────────────────────────
        if open_usdc + cost > config.MAX_TOTAL_OPEN_USDC:
            print(f"   ⛔ 跳過（總開倉 ${open_usdc + cost:.2f} > ${config.MAX_TOTAL_OPEN_USDC}）: {title}")
            results.append(TrendExecResult(**base, mode=mode, status="skipped",
                                           order_id="", error="總開倉超限"))
            done.add(key)
            continue

        if not config.LIVE_MODE:
            print(f"   🟡 DRY-RUN BUY {o.get('outcome', '?')} @ {o.get('suggested_price', 0):.3f}"
                  f"  ${cost:.2f}  conf={o.get('confidence', 0):.2f}  {title}")
            results.append(TrendExecResult(**base, mode="dry-run", status="dry-run",
                                           order_id="", error=""))
        else:
            # ⚠️ LIVE：送真實單
            print(f"   🔴 LIVE BUY {o.get('outcome', '?')} @ {o.get('suggested_price', 0):.3f}"
                  f"  ${cost:.2f}  {title}")
            order_id, error = _place_order_live(o)
            status = "error" if error else "submitted"
            if error:
                print(f"      ✗ {error}")
            else:
                print(f"      ✓ order_id={order_id}")
                open_usdc += cost
            results.append(TrendExecResult(**base, mode="live", status=status,
                                           order_id=order_id, error=error))
        done.add(key)

    _append(results)
    _save_hashes(done)
    ok = sum(1 for r in results if r.status in ("submitted", "dry-run"))
    err = sum(1 for r in results if r.status == "error")
    print(f"\n   ✅ 執行完成: {ok} 筆成功，{err} 筆失敗")
    return results
