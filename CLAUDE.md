# Polymarket Whale Copy Trading Bot — 專案上下文

## ⚠️ 安全守則（絕對不能違反）
- **任何真實交易前**，必須先有 dry-run 模式驗證，且讓 Koh 明確確認後才能切換 LIVE_MODE=true
- 私鑰只放在 `~/.polymarket/.env`，絕對不能 hardcode 或 commit
- `.gitignore` 已排除 `.env*` 和 `data/backtest/`
- `LIVE_MODE` 目前在 `.github/workflows/pipeline.yml` 裡寫死為 `false`

---

## 專案概覽
**策略**：跟單 Polymarket 高獲利鯨魚，買入與其相同的 outcome，但縮小金額（×0.001，上限 $10/單）。

**部署**：GitHub Actions 每 30 分鐘自動跑一次，狀態檔 commit 回 repo。

**根目錄**：`C:\Users\lenov\Desktop\polytest_trading_bot\polytest\`

---

## 模組結構

```
core/
  config.py            讀取 ~/.polymarket/.env 所有設定
  polymarket_client.py Gamma/CLOB/Data API 封裝
  dns_patch.py         繞過 ISP DNS 攔截（家中 ISP 封鎖 *.polymarket.com）

whale_copy/
  discovery.py         從排行榜找高獲利鯨魚
  monitor.py           掃描鯨魚新交易 → data/signals.jsonl
  signal_generator.py  過濾 raw signal → data/pending_orders.jsonl
  executor.py          執行下單（目前 dry-run）
  market_classifier.py 把市場分類為 sports / crypto / other

backtest/
  pull_historical.py   拉鯨魚歷史 BUY trades + 市場結算狀態
  simulator.py         模擬跟單邏輯，計算 PnL
  analyzer.py          輸出回測報告（IS/OOS 分析）
  fees.py              手續費常數（taker 0.20%）

scripts/
  run_pipeline.py      ★ 主入口：monitor → signal_generator → executor → TG
  run_whale_discovery.py  手動重跑 whale discovery
  run_backtest.py      手動跑完整回測
  run_pnl_tracker.py   追蹤 dry-run 訂單的前向 PnL
  run_expand_discovery.py 放寬條件重跑 discovery
  check_balance.py     查錢包 USDC 餘額
  check_config.py      確認 .env 設定正確
  generate_api_keys.py 產生 Polymarket CLOB API Key
```

---

## 關鍵設定（signal_generator.py）

```python
MIN_WHALE_SIZE_USDC = 500.0      # 鯨魚單最小規模
MIN_MARKET_HOURS_LEFT = 6.0      # 距結算 < 6h 不跟
MIN_ENTRY_PRICE = 0.20           # entry price alpha 區間
MAX_ENTRY_PRICE = 0.80
SLIPPAGE_BUFFER = 0.005          # 0.5% slippage

# ★ 注意：dry-run 期間故意設成 set()（收集所有類別數據）
# 上 live 前必須改回 {"other"}（sports 回測 IS = -24%，other IS/OOS = +30%/+27%）
ALLOWED_CATEGORIES: set[str] = set()

WHALE_BLACKLIST = {"0xbddf61af533ff524d27154e589d2d7a81510c684"}  # Countryside（回測虧損）
```

---

## 關鍵設定（pipeline.yml / .env）

```
LIVE_MODE=false          # ← 上 live 前在 pipeline.yml 改成 true
MAX_BET_USDC=10          # 單筆上限
MAX_TOTAL_OPEN_USDC=100  # 總開倉上限
WHALE_FOLLOW_RATIO=0.001 # 跟單比例（鯨魚單 × 0.001）
INITIAL_CAPITAL_USDC=100 # 初始資金（記錄用）
```

---

## 當前鯨魚池（data/whales.json）

| pseudonym | proxy_wallet | 備注 |
|-----------|-------------|------|
| newdogbeginning（Tinted-Consciousness） | 0xfea31bc088000ff909... | 主力，90d OOS +17% |
| Countryside | 0xbddf61af533... | **黑名單**（回測 -$32，47% 勝率） |

**⚠️ 實際上只有 Tinted 一隻有效鯨魚，風險集中。**

---

## 回測核心結論（90 天，Split: IS=30-90d, OOS=0-30d）

| 類別 | IS ROI | OOS ROI | 結論 |
|------|--------|---------|------|
| other（政治/經濟） | +30.7% | +27.3% | ✅ 穩定 alpha，上 live 用這個 |
| sports | -24.4% | +15.5% | ❌ 嚴重 selection bias，捨棄 |
| 全類別（$500+） | -3.6% | +17.5% | 可接受，但 other 更好 |

---

## 資料檔案狀態

| 檔案 | 說明 |
|------|------|
| `data/signals.jsonl` | 425 筆 raw 訊號（monitor 產出） |
| `data/processed_signal_hashes.json` | 255 筆已處理 hash |
| `data/rejected_signals.jsonl` | 295 筆被拒訊號 + 原因 |
| `data/pending_orders.jsonl` | **目前為空**（還沒有通過所有過濾的訊號） |
| `data/executed_orders.jsonl` | **不存在**（尚未執行任何單） |
| `data/whales_expanded.json` | 只有 2 隻（同 whales.json，擴展搜尋未找到新鯨魚） |

---

## 目前進度與待辦

### 🟢 已完成
- 全套 pipeline（monitor → signal_generator → executor → TG）
- GitHub Actions 自動化（每 30 分鐘）
- 90 天回測 + alpha 過濾
- dry-run executor

### 🔴 上 live 前必須做
1. **等第一筆 dry-run 訊號通過**（剛 re-queue 了 7 筆，等 GHA 下一輪）
2. **把 ALLOWED_CATEGORIES 改回 `{"other"}`**（在 signal_generator.py）
3. **確認 Polygon 錢包有 USDC**（建議 $50-100；用 `python -m scripts.check_balance` 查）
4. **在 pipeline.yml 改 `LIVE_MODE=true`**（Koh 明確確認後才動）

### 🟡 重要但非緊急
5. **擴大鯨魚池**：目前只有 1 隻有效鯨魚，需要重跑 discovery 或手動加入
6. **實作 DAILY_LOSS_LIMIT_USDC**：config 有這個值但 executor.py 沒有用到
7. **部位監控**：目前無法看持倉狀態或浮盈虧

### ⚪ 未來優化
8. **Forward PnL 驗證**：等 pending_orders 累積 20-30 筆後跑 `run_pnl_tracker.py`
9. **Whale re-discovery**：定期更新鯨魚池（鯨魚策略會演化）

---

## 常見操作指令

```powershell
# 切到專案目錄（必須先做）
cd C:\Users\lenov\Desktop\polytest_trading_bot\polytest

# 手動跑一次 pipeline（需接手機熱點，家中 ISP 封鎖 polymarket.com）
python -m scripts.run_pipeline

# 查 USDC 餘額
python -m scripts.check_balance

# 查當前訊號狀態
python -m scripts._signals_stats

# 重跑 whale discovery
python -m scripts.run_whale_discovery

# 重跑回測
python -m scripts.run_backtest

# 追蹤前向 PnL（需有 pending_orders 才有數據）
python -m scripts.run_pnl_tracker
```

---

## 已知問題與解法

| 問題 | 解法 |
|------|------|
| ISP 封鎖 polymarket.com | 接手機熱點再跑 |
| UnicodeEncodeError（Windows PowerShell） | 腳本開頭加 `sys.stdout.reconfigure(encoding='utf-8')` |
| git push 被拒（GHA 也在 commit） | `git fetch origin` → 手動合併 → `git push` |
| Data API offset > 3000 回傳 400 | `_fetch_trades_page` 返回 None 時停止分頁 |
| Gamma API 找不到已關閉市場 | fallback 到 CLOB API（`_fetch_market_clob`） |

---

## GitHub
Repo: `https://github.com/King102681/polymarket-bot`  
Actions: `https://github.com/King102681/polymarket-bot/actions`
