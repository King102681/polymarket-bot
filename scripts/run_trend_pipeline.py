"""策略 B 主入口：趨勢抓取 → 市場配對 → 規則式評估 → dry-run → Telegram。

執行：
    python -m scripts.run_trend_pipeline

網路：Polymarket 在家會被 ISP 攔截，需接手機熱點 / VPN；newsnow 不受該攔截影響。
規則版不呼叫任何 AI API，完全免費。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core  # noqa  DNS bypass + UTF-8

import requests

from core import config
from core.polymarket_client import PolymarketClient
from trend_trade import executor, market_matcher, signal_evaluator, trend_fetcher


def send_telegram(text: str) -> bool:
    if not config.TG_BOT_TOKEN or not config.TG_CHAT_ID:
        print("⚠️ TG 未設定，跳過推送")
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


def main() -> None:
    # 規則版不需要 ANTHROPIC_API_KEY；dry-run 讀取市場/訂單簿是公開端點，無需金鑰。
    # 只有 LIVE_MODE 真實下單才需要 Polymarket 金鑰（送單時才驗證）。
    if config.LIVE_MODE:
        config.validate()
    t0 = time.time()
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'=' * 60}\n 🌊 Trend Pipeline @ {ts}\n{'=' * 60}")

    # ── 1. 抓趨勢 ───────────────────────────────────────────────────
    print("\n[1/4] trend_fetcher.fetch_trends()")
    trends = trend_fetcher.fetch_trends()
    hot = [t for t in trends if t.heat >= config.TREND_MIN_HEAT][: config.TREND_MAX_PER_RUN]
    print(f"  共 {len(trends)} 條，熱度≥{config.TREND_MIN_HEAT} 取前 {len(hot)} 條評估")
    if not hot:
        print("  無夠熱話題，結束")
        return

    client = PolymarketClient()

    # ── 2. 配對市場（關鍵字字典 + Gamma 搜尋）─────────────────────
    print("\n[2/4] market_matcher.find_candidates()")
    pairs = market_matcher.find_candidates(hot, client)
    if not pairs:
        print("  無配對市場，結束")
        return

    # ── 3. 規則式評估下注 ─────────────────────────────────────────
    print(f"\n[3/4] signal_evaluator.evaluate()（{len(pairs)} 組）")
    orders, _rejected = signal_evaluator.evaluate(pairs, client)

    # ── 4. 執行 + 推送 ─────────────────────────────────────────────
    print("\n[4/4] executor.execute_all()")
    results = executor.execute_all(orders)

    if results:
        mode_tag = "🔴 LIVE" if config.LIVE_MODE else "🟡 dry-run"
        header = f"🌊 <b>TrendRadar 策略</b>  {mode_tag}  @ {ts}\n━━━━━━━━━━━━━━━━━━━\n"
        body = "\n".join(
            f"{'✅' if r.status in ('submitted', 'dry-run') else '⛔'} "
            f"BUY {r.outcome} @ {r.suggested_price:.3f}  ${r.cost_usdc:.2f}  "
            f"conf={r.confidence:.2f}\n   {r.market_title[:60]}\n   💭 {r.reasoning[:80]}"
            for r in results
        )
        send_telegram(header + body)

    print(f"\n✅ Trend Pipeline 完成（{time.time() - t0:.1f}s）")


if __name__ == "__main__":
    main()
