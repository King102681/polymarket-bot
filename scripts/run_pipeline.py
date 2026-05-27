"""一鍵跑 monitor → signal_generator → Telegram 推送。

執行：
    python -m scripts.run_pipeline

排程方式擇一：
    1. PowerShell loop: scripts/run_loop.ps1
    2. Windows Task Scheduler 排程
    3. GitHub Actions cron: .github/workflows/pipeline.yml
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core  # noqa  # DNS bypass + UTF-8

import requests

from core import config
from whale_copy import monitor, signal_generator, executor


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


def format_order(o) -> str:
    mode_tag = "🔴 <b>LIVE 已下單</b>" if config.LIVE_MODE else "🟡 <b>dry-run</b>"
    return (
        f"🐋 <b>跟單訊號</b>  {mode_tag}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"鯨魚: <i>{o.whale_pseudonym}</i>  （鯨魚單 ${o.whale_size_usdc:,.0f}）\n"
        f"市場: {o.market_title[:80]}\n"
        f"類別: <code>{o.market_category}</code>\n"
        f"動作: BUY <b>{o.outcome}</b> @ {o.suggested_price:.3f}\n"
        f"下單: ${o.suggested_cost_usdc:.2f} USDC → {o.suggested_size:.2f} shares\n"
        + (f"⚠️ {o.notes}\n" if o.notes else "")
    )


def format_execution(r) -> str:
    """executor 執行結果的 Telegram 格式。"""
    icon = {"submitted": "✅", "dry-run": "🟡", "skipped": "⛔", "error": "❌"}.get(r.status, "?")
    detail = ""
    if r.status == "submitted":
        detail = f"order_id: <code>{r.order_id}</code>"
    elif r.status == "error":
        detail = f"錯誤: {r.error[:80]}"
    elif r.status == "skipped":
        detail = r.error[:80]
    return (
        f"{icon} <b>{r.status.upper()}</b>  BUY {r.outcome} @ {r.suggested_price:.3f}\n"
        f"   {r.market_title[:60]}\n"
        + (f"   {detail}\n" if detail else "")
    )


def main() -> None:
    t0 = time.time()
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'=' * 60}")
    print(f" 🚀 Pipeline @ {ts}")
    print(f"{'=' * 60}")

    print("\n[1/2] monitor.scan_once()")
    new_raw = monitor.scan_once()

    print("\n[2/3] signal_generator.process_all()")
    new_orders, rejected = signal_generator.process_all()

    print("\n[3/3] executor.execute_all()")
    exec_results = executor.execute_all(new_orders)

    # ── Telegram 推送 ─────────────────────────────────────────────────
    if exec_results:
        mode_tag = "🔴 LIVE" if config.LIVE_MODE else "🟡 dry-run"
        header = (
            f"🐋 <b>新跟單執行</b>  {mode_tag}  @ {ts}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
        )
        body = "\n".join(format_execution(r) for r in exec_results)
        send_telegram(header + body)
    elif new_raw and not new_orders:
        # 有原始訊號但全被過濾，靜默（不再每次推送）
        print(f"   raw 訊號 {len(new_raw)} 筆，全被過濾，不推送")

    elapsed = time.time() - t0
    print(f"\n✅ Pipeline 完成（{elapsed:.1f}s）")


if __name__ == "__main__":
    main()
