"""策略 B 乾跑匯總（stage 1）：只抓 newsnow 真實趨勢 + 算熱度。

不碰 Claude、不碰 Polymarket、不下任何單——用來在沒有 ANTHROPIC_API_KEY、
沒接熱點時，先確認資料源正常、熱度排名是否合理。
完整配對/評估/下單（stage 2-4）見 scripts.run_trend_pipeline（需 key + 熱點）。

    python -m scripts._trend_dryrun_summary
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core  # noqa  DNS bypass + UTF-8

from core import config
from trend_trade import trend_fetcher


def main() -> None:
    plats = [p.strip() for p in config.TREND_PLATFORMS.split(",") if p.strip()]
    print(f"平台（{len(plats)}）: {', '.join(plats)}")
    print("抓取中（newsnow，免 key）...\n")

    trends = trend_fetcher.fetch_trends()
    hot = [t for t in trends if t.heat >= config.TREND_MIN_HEAT]

    print(f"去重後話題數: {len(trends)}    熱度門檻 TREND_MIN_HEAT={config.TREND_MIN_HEAT}\n")
    if not trends:
        print("⚠️ 抓到 0 個話題——可能 newsnow 不可達，或回傳結構與解析器不符。")
        print("   把任一平台的 raw response 貼給我，我調整 _extract_items。")
        return

    print(f"{'':2}{'熱度':>5} {'平台':>3} {'分鐘':>5}  標題")
    print("-" * 64)
    for t in trends[:20]:
        mark = "🔥" if t.heat >= config.TREND_MIN_HEAT else "  "
        print(f"{mark}{t.heat:>5.1f} {t.frequency:>3} {t.minutes_tracked:>5.0f}  {t.title[:44]}")
    print("-" * 64)

    print(f"\n≥門檻、會送進 stage 2 配對的: {len(hot)} 個"
          f"（每輪上限 TREND_MAX_PER_RUN={config.TREND_MAX_PER_RUN}）")
    print("stage 2 配對 + stage 3 Claude 評估 需要 ANTHROPIC_API_KEY + Polymarket 連線。")


if __name__ == "__main__":
    main()
