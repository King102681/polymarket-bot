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
from whale_copy import monitor, signal_generator


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
    mode_tag = "🔴 <b>LIVE</b>" if config.LIVE_MODE else "🟡 dry-run"
    return (
        f"🐋 <b>新跟單訊號</b>  {mode_tag}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"鯨魚: <i>{o.whale_pseudonym}</i>\n"
        f"市場: {o.market_title[:80]}\n"
        f"類別: <code>{o.market_category}</code>\n"
        f"動作: BUY <b>{o.outcome}</b> @ {o.suggested_price:.3f}\n"
        f"建議: ${o.suggested_cost_usdc:.2f} USDC × {o.suggested_size:.2f} shares\n"
        f"鯨魚單規模: ${o.whale_size_usdc:,.0f}\n"
        + (f"⚠️ {o.notes}\n" if o.notes else "")
    )


def main() -> None:
    t0 = time.time()
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'=' * 60}")
    print(f" 🚀 Pipeline @ {ts}")
    print(f"{'=' * 60}")

    print("\n[1/2] monitor.scan_once()")
    new_raw = monitor.scan_once()

    print("\n[2/2] signal_generator.process_all()")
    new_orders, rejected = signal_generator.process_all()

    if new_orders:
        print(f"\n📡 推送 {len(new_orders)} 筆新訊號到 Telegram...")
        for o in new_orders:
            ok = send_telegram(format_order(o))
            print(f"   {'✓' if ok else '✗'} {o.market_title[:50]}")
    elif new_raw:
        # 有原始訊號但全被過濾，發個 summary
        send_telegram(
            f"📊 Pipeline @ {ts}\n"
            f"raw 訊號: {len(new_raw)}  通過: 0  拒絕: {len(rejected)}\n"
            f"<i>本輪無新跟單建議</i>"
        )

    elapsed = time.time() - t0
    print(f"\n✅ Pipeline 完成（{elapsed:.1f}s）")


if __name__ == "__main__":
    main()
