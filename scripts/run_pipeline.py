"""一鍵跑 monitor → 所有策略 → Telegram 推送。

三個策略同時運行，各自輸出獨立的訂單檔案：
  data/pending_orders_political.jsonl    政治/地緣市場
  data/pending_orders_sports_live.jsonl  體育直播跟單
  data/pending_orders_open.jsonl         開放探索

執行：
    python -m scripts.run_pipeline
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core  # noqa  # DNS bypass + UTF-8

import requests

from core import config
from whale_copy import monitor, executor
from whale_copy import signal_generator
from whale_copy.strategies import STRATEGIES


def send_telegram(text: str) -> bool:
    if not config.TG_BOT_TOKEN or not config.TG_CHAT_ID:
        print("⚠️ TG_BOT_TOKEN 或 TG_CHAT_ID 未設定，跳過推送")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{config.TG_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": config.TG_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        return r.ok
    except Exception as e:
        print(f"⚠️ TG 推送失敗: {e}")
        return False


def format_execution(r, strategy_display: str, emoji: str) -> str:
    icon = {"submitted": "✅", "dry-run": "🟡", "skipped": "⛔", "error": "❌"}.get(r.status, "?")
    detail = ""
    if r.status == "submitted":
        detail = f"order_id: <code>{r.order_id}</code>"
    elif r.status in ("error", "skipped"):
        detail = r.error[:80] if r.error else ""
    return (
        f"{icon} [{emoji} {strategy_display}]  BUY {r.outcome} @ {r.suggested_price:.3f}\n"
        f"   {r.market_title[:60]}\n"
        + (f"   {detail}\n" if detail else "")
    )


def main() -> None:
    t0 = time.time()
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'=' * 60}")
    print(f" 🚀 Pipeline @ {ts}")
    print(f"{'=' * 60}")

    # ── Step 1: 掃描鯨魚最新交易 ─────────────────────────────────────
    print("\n[1/2] monitor.scan_once()")
    new_raw = monitor.scan_once()

    # ── Step 2: 每個策略分別過濾 ─────────────────────────────────────
    print("\n[2/2] signal_generator — 三策略並行")
    all_exec_results = []

    for strat in STRATEGIES.values():
        if not strat.enabled:
            print(f"  [{strat.name}] 已停用，跳過")
            continue

        new_orders, rejected = signal_generator.process_all(strat)

        # 每個策略的訂單分別送給 executor
        exec_results = executor.execute_all(new_orders)
        all_exec_results.extend(exec_results)

        # 各策略各自推送 Telegram
        if exec_results:
            mode_tag = "🔴 LIVE" if config.LIVE_MODE else "🟡 dry-run"
            header = (
                f"{strat.emoji} <b>{strat.display_name}</b>  {mode_tag}  @ {ts}\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
            )
            body = "\n".join(
                format_execution(r, strat.display_name, strat.emoji)
                for r in exec_results
            )
            send_telegram(header + body)

    # ── 沒有任何訂單時，靜默（不每次推空訊息）─────────────────────
    if not all_exec_results:
        total_raw = len(new_raw) if new_raw else 0
        print(f"\n   raw 訊號 {total_raw} 筆，全策略均無通過")

    elapsed = time.time() - t0
    print(f"\n✅ Pipeline 完成（{elapsed:.1f}s）")


if __name__ == "__main__":
    main()
