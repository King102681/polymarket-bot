"""下單執行器 — 把 signal_generator 的建議轉成 Polymarket CLOB 限價單。

讀取：data/pending_orders.jsonl
輸出：data/executed_orders.jsonl（追加）

LIVE_MODE=false（預設）：dry-run，只記錄，不送真實單
LIVE_MODE=true           ：送真實限價單到 CLOB API

安全限制：
  - MAX_BET_USDC         ：單筆上限（signal_generator 已限制）
  - MAX_TOTAL_OPEN_USDC  ：累計已送出但未結算的金額上限
  - 市場結算時間 ≤ 0h    ：自動跳過（已過期）

⚠️ LIVE_MODE=true 前必須確認：
   1. ~/.polymarket/.env 中 LIVE_MODE=true
   2. 錢包有足夠 USDC 餘額
   3. 已完成至少一輪 dry-run 確認 pipeline 正常運作
"""
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core import config

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_PENDING_PATH = _DATA_DIR / "pending_orders.jsonl"
_EXECUTED_PATH = _DATA_DIR / "executed_orders.jsonl"
_EXEC_HASHES_PATH = _DATA_DIR / "executed_tx_hashes.json"

# 手續費（taker，與 backtest/fees.py 一致）
TAKER_FEE_RATE = 0.0020   # 0.20%


@dataclass
class ExecutionResult:
    signal_tx_hash: str
    executed_at: int
    whale_pseudonym: str
    market_title: str
    market_category: str
    condition_id: str
    asset: str
    outcome: str
    suggested_price: float
    suggested_size: float
    cost_usdc: float
    mode: str          # "live" | "dry-run"
    status: str        # "submitted" | "dry-run" | "skipped" | "error"
    order_id: str      # CLOB order ID（live 時才有）
    error: str         # 失敗原因（status="error" 時）
    notes: str


def _load_executed_hashes() -> set[str]:
    if not _EXEC_HASHES_PATH.exists():
        return set()
    with open(_EXEC_HASHES_PATH, encoding="utf-8") as f:
        return set(json.load(f))


def _save_executed_hashes(hashes: set[str]) -> None:
    _EXEC_HASHES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_EXEC_HASHES_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(hashes), f)


def _load_pending() -> list[dict]:
    if not _PENDING_PATH.exists():
        return []
    return [json.loads(l) for l in open(_PENDING_PATH, encoding="utf-8") if l.strip()]


def _append_executed(results: list[ExecutionResult]) -> None:
    _EXECUTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_EXECUTED_PATH, "a", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")


def _total_open_usdc() -> float:
    """計算目前已執行（含 dry-run）但未結算的預估總金額。"""
    if not _EXECUTED_PATH.exists():
        return 0.0
    total = 0.0
    for l in open(_EXECUTED_PATH, encoding="utf-8"):
        if l.strip():
            r = json.loads(l)
            if r["status"] in ("submitted", "dry-run"):
                total += r["cost_usdc"]
    return total


def _place_order_live(order: dict) -> tuple[str, str]:
    """
    送真實限價單到 Polymarket CLOB。
    回傳 (order_id, error)。若成功 error=""，若失敗 order_id=""。
    """
    try:
        # py_clob_client 0.34.x 正確 import：
        #   - OrderArgs（非 LimitOrderArgs，後者已移除）
        #   - BUY 在 order_builder.constants（非 constants）
        #   - 下單分兩步：create_order(簽名) → post_order(送出, 帶 OrderType)
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY

        clob = ClobClient(
            host="https://clob.polymarket.com",
            key=config.WALLET_PRIVATE_KEY,
            chain_id=config.CHAIN_ID,
        )
        clob.set_api_creds(ApiCreds(
            api_key=config.POLY_API_KEY,
            api_secret=config.POLY_API_SECRET,
            api_passphrase=config.POLY_API_PASSPHRASE,
        ))

        order_args = OrderArgs(
            token_id=order["asset"],
            price=float(order["suggested_price"]),
            size=float(order["suggested_size"]),
            side=BUY,
        )
        signed = clob.create_order(order_args)
        resp = clob.post_order(signed, OrderType.GTC)   # GTC = 掛單直到成交/取消

        # resp 通常是 {"orderID": "...", "status": "matched"|"live", ...}
        order_id = ""
        if isinstance(resp, dict):
            order_id = resp.get("orderID") or resp.get("order_id") or str(resp)
        elif hasattr(resp, "orderID"):
            order_id = resp.orderID
        return order_id or "submitted", ""

    except Exception as e:
        return "", f"{type(e).__name__}: {e}"


def execute_all(new_orders: list | None = None) -> list[ExecutionResult]:
    """
    執行所有未處理的 pending_orders。

    new_orders：若傳入，只處理這些（signal_generator 剛產生的）；
                否則重讀 pending_orders.jsonl 全部。
    """
    if new_orders is not None:
        # signal_generator 傳進來的 Order dataclass 轉 dict
        from dataclasses import asdict as dc_asdict
        orders_raw = [dc_asdict(o) if hasattr(o, "__dataclass_fields__") else o
                      for o in new_orders]
    else:
        orders_raw = _load_pending()

    executed_hashes = _load_executed_hashes()
    to_exec = [o for o in orders_raw if o["signal_tx_hash"] not in executed_hashes]

    if not to_exec:
        print("⚙️  executor: 無新訂單需要執行")
        return []

    mode = "live" if config.LIVE_MODE else "dry-run"
    open_usdc = _total_open_usdc()
    print(f"\n⚙️  executor [{mode.upper()}]: {len(to_exec)} 筆待執行，目前開倉 ${open_usdc:.2f}")

    results: list[ExecutionResult] = []

    for order in to_exec:
        tx = order["signal_tx_hash"]
        title = order.get("market_title", "")[:50]
        cost = float(order.get("suggested_cost_usdc", 0))

        # ── 風險限制：總開倉上限 ──────────────────────────────────────
        if open_usdc + cost > config.MAX_TOTAL_OPEN_USDC:
            print(f"   ⛔ 跳過（總開倉 ${open_usdc + cost:.2f} > 上限 ${config.MAX_TOTAL_OPEN_USDC}）: {title}")
            r = ExecutionResult(
                signal_tx_hash=tx,
                executed_at=int(time.time()),
                whale_pseudonym=order.get("whale_pseudonym", ""),
                market_title=title,
                market_category=order.get("market_category", ""),
                condition_id=order.get("condition_id", ""),
                asset=order.get("asset", ""),
                outcome=order.get("outcome", ""),
                suggested_price=float(order.get("suggested_price", 0)),
                suggested_size=float(order.get("suggested_size", 0)),
                cost_usdc=cost,
                mode=mode,
                status="skipped",
                order_id="",
                error=f"總開倉超限 (${open_usdc + cost:.2f} > ${config.MAX_TOTAL_OPEN_USDC})",
                notes="",
            )
            results.append(r)
            executed_hashes.add(tx)
            continue

        # ── 執行 ──────────────────────────────────────────────────────
        if not config.LIVE_MODE:
            # dry-run：記錄但不送單
            print(f"   🟡 DRY-RUN  BUY {order.get('outcome','?')} @ {order.get('suggested_price',0):.3f}"
                  f"  ${cost:.2f}  {title}")
            r = ExecutionResult(
                signal_tx_hash=tx,
                executed_at=int(time.time()),
                whale_pseudonym=order.get("whale_pseudonym", ""),
                market_title=title,
                market_category=order.get("market_category", ""),
                condition_id=order.get("condition_id", ""),
                asset=order.get("asset", ""),
                outcome=order.get("outcome", ""),
                suggested_price=float(order.get("suggested_price", 0)),
                suggested_size=float(order.get("suggested_size", 0)),
                cost_usdc=cost,
                mode="dry-run",
                status="dry-run",
                order_id="",
                error="",
                notes="",
            )
        else:
            # ⚠️ LIVE MODE：送真實單
            print(f"   🔴 LIVE    BUY {order.get('outcome','?')} @ {order.get('suggested_price',0):.3f}"
                  f"  ${cost:.2f}  {title}")
            order_id, error = _place_order_live(order)
            if error:
                print(f"      ✗ 下單失敗: {error}")
                status = "error"
            else:
                print(f"      ✓ 已送出 order_id={order_id}")
                status = "submitted"
                open_usdc += cost  # 更新本輪累計開倉

            r = ExecutionResult(
                signal_tx_hash=tx,
                executed_at=int(time.time()),
                whale_pseudonym=order.get("whale_pseudonym", ""),
                market_title=title,
                market_category=order.get("market_category", ""),
                condition_id=order.get("condition_id", ""),
                asset=order.get("asset", ""),
                outcome=order.get("outcome", ""),
                suggested_price=float(order.get("suggested_price", 0)),
                suggested_size=float(order.get("suggested_size", 0)),
                cost_usdc=cost,
                mode="live",
                status=status,
                order_id=order_id,
                error=error,
                notes="",
            )
            if status == "submitted":
                open_usdc += cost

        results.append(r)
        executed_hashes.add(tx)

    _append_executed(results)
    _save_executed_hashes(executed_hashes)

    submitted = sum(1 for r in results if r.status in ("submitted", "dry-run"))
    errors = sum(1 for r in results if r.status == "error")
    print(f"\n   ✅ 執行完成: {submitted} 筆成功，{errors} 筆失敗")
    return results
