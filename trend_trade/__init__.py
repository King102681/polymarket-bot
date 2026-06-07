"""策略 B：TrendRadar × Claude 自主交易模組。

資料流：
    trend_fetcher  → 從 newsnow（TrendRadar 資料源）抓多平台熱門話題 + 計算熱度
    market_matcher → Claude 把中文話題映射成英文關鍵字並配對 Polymarket 市場
    signal_evaluator → Claude 判斷是否下注，產生 dry-run 訂單建議
    executor       → dry-run 記錄（LIVE_MODE=true 才送真實單）

主入口：scripts/run_trend_pipeline.py
"""
