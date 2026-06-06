# Polymarket Whale Copy Trading Bot — 專案上下文

## ⚠️ 安全守則（絕對不能違反）
- **任何真實交易前**，必須先有 dry-run 模式驗證，且讓 Koh 明確確認後才能切換 LIVE_MODE=true
- 私鑰只放在 `~/.polymarket/.env`，絕對不能 hardcode 或 commit
- `.gitignore` 已排除 `.env*` 和 `data/backtest/`
- `LIVE_MODE` 目前在 `.github/workflows/pipeline.yml` 裡寫死為 `false`

---

## 專案概覽
**策略**：跟單 Polymarket 高獲利鯨魚，買入與其相同的 outcome，縮小金額（×0.001，上限 $10/單）。

**部署**：GitHub Actions 每 **5 分鐘**自動跑一次（2026-06-03 更新），狀態檔 commit 回 repo。

**根目錄**：`C:\Users\lenov\Desktop\polytest_trading_bot\polytest\`

**GitHub**：`https://github.com/King102681/polymarket-bot`

---

## 模組結構

```
core/
  config.py            讀取 ~/.polymarket/.env 所有設定
  polymarket_client.py Gamma/CLOB/Data API 封裝
  dns_patch.py         繞過 ISP DNS 攔截（家中 ISP 封鎖 *.polymarket.com）

whale_copy/
  discovery.py         從排行榜找高獲利鯨魚（基礎版）
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
  run_pipeline.py        ★ 主入口：monitor → signal_generator → executor → TG
  run_smart_discovery.py ★ 智慧鯨魚發現（篩 other≥25% 且 0.20-0.80 價格比例≥20%）
  run_whale_discovery.py   舊版發現（已不使用，discovery.yml 已改用 smart 版）
  run_backtest.py          手動跑完整回測
  run_pnl_tracker.py       追蹤 dry-run 訂單前向 PnL
  check_balance.py         查錢包 USDC 餘額
  check_config.py          確認 .env 設定正確
  generate_api_keys.py     產生 Polymarket CLOB API Key
```

---

## 關鍵設定（signal_generator.py）

```python
MIN_WHALE_SIZE_USDC = 100.0       # 降低門檻（捕捉 Spirit of Ukraine 類的政治市場早期試水單）
MIN_MARKET_HOURS_LEFT = 6.0       # 距結算 < 6h 不跟（現在）
MIN_ENTRY_HOURS_REMAINING = 168.0 # 鯨魚進場時市場剩餘 < 7 天不跟（過濾短期賽事）
MIN_ENTRY_PRICE = 0.20            # entry price alpha 區間
MAX_ENTRY_PRICE = 0.87
SLIPPAGE_BUFFER = 0.005           # 0.5% slippage

# ★ dry-run 期間設成 set()（收集所有類別數據）
# 上 live 前必須改回 {"other"}（sports 回測 IS=-24%，other IS/OOS=+30%/+27%）
ALLOWED_CATEGORIES: set[str] = set()

WHALE_BLACKLIST = {"0xbddf61af533ff524d27154e589d2d7a81510c684"}  # Countryside（回測虧損）
```

---

## 關鍵設定（pipeline.yml / .env）

```
LIVE_MODE=false          # ← 上 live 前改成 true（需 Koh 明確確認）
MAX_BET_USDC=10          # 單筆上限
MAX_TOTAL_OPEN_USDC=100  # 總開倉上限
WHALE_FOLLOW_RATIO=0.001 # 跟單比例（鯨魚單 × 0.001）
INITIAL_CAPITAL_USDC=100 # 初始資金（記錄用）
```

---

## 當前鯨魚池（data/whales.json）

| pseudonym | proxy_wallet | 備注 |
|-----------|-------------|------|
| swisstony | 0x204f72f35326db9321... | ROI 6.9%，other 50%，usable price 52% ✅ |
| The Spirit of Ukraine>UMA | 0x0c0e270cf879583d6a... | ROI 4.3%，other 80%，usable price 30% ✅ |

**已移除**：
- newdogbeginning（Tinted）：大單全在 0.995+ 市場，無法跟單
- Countryside：黑名單（回測 -$32，47% 勝率）

**鯨魚發現邏輯（run_smart_discovery.py）**：
- Leaderboard 30d profit + volume 各抓 500 筆
- 門檻：profit ≥ $3k，volume ≥ $15k，value_now ≥ $3k
- 額外篩選：other 類別 ≥ 25%，且 other 交易中 0.20-0.80 價格比例 ≥ 20%
- 自動更新 whales.json（找到 ≥ 2 隻新鯨魚時）

---

## 回測核心結論（90 天，Split: IS=30-90d, OOS=0-30d）

| 類別 | IS ROI | OOS ROI | 結論 |
|------|--------|---------|------|
| other（政治/經濟/地緣） | +30.7% | +27.3% | ✅ 穩定 alpha，上 live 用這個 |
| sports | -24.4% | +15.5% | ❌ 嚴重 selection bias，捨棄 |
| 全類別（$500+） | -3.6% | +17.5% | 可接受，但 other 更好 |

---

## 已診斷的核心問題（2026-06-03）

### 問題一：30 分鐘輪詢太慢
鯨魚進場 → 市場立刻重新定價 → 30 分鐘後查訂單簿已是 0.995 → 正確拒絕但錯失機會。
**修正**：pipeline 改為每 5 分鐘（commit fb93e04）

### 問題二：當日快結算市場（當日球賽）
鯨魚在法網、NBA 場次剛開始時下注，我們根本趕不上。
**修正**：新增 MIN_ENTRY_HOURS_REMAINING=24h 過濾器（commit fb93e04）

### 問題三：whales.json 被 GHA 每週清空
舊 discovery 腳本門檻太嚴，leaderboard 只回 50 筆結果全部被濾掉 → 空列表覆蓋 whales.json。
**修正**：discovery.yml 改用 run_smart_discovery.py（commit 2562fac）

### 問題四：TG Bot Token 失效
舊 token 401 Unauthorized，Telegram 從未收到任何訊息。
**修正**：2026-06-03 由 Koh 手動更新 .env 和 GitHub Secrets

---

## 資料檔案狀態（2026-06-03）

| 檔案 | 說明 |
|------|------|
| `data/signals.jsonl` | ~1000+ 筆 raw 訊號 |
| `data/processed_signal_hashes.json` | ~260 筆已處理 hash |
| `data/rejected_signals.jsonl` | ~600+ 筆被拒 + 原因 |
| `data/pending_orders.jsonl` | **目前為空**（尚無訊號通過所有過濾） |
| `data/executed_orders.jsonl` | **不存在**（尚未執行任何單） |
| `data/whales_smart.json` | smart discovery 輸出（備份用） |

---

## 待辦清單

### 🔴 上 live 前必須做
1. **等第一筆 dry-run 訊號通過** → Telegram 會推送（TG 已修好）
2. **把 ALLOWED_CATEGORIES 改回 `{"other"}`**（signal_generator.py 第 55 行）
3. **確認 Polygon 錢包有 USDC**（`python -m scripts.check_balance`）
4. **在 pipeline.yml 改 `LIVE_MODE=true`**（Koh 明確確認後才動）

### 🟡 重要但非緊急
5. **監控新鯨魚效果**：swisstony 和 Ukraine 剛加入，觀察幾天看訊號質量
6. **定期重跑 smart discovery**：每月一次補充新鯨魚
7. **Forward PnL 追蹤**：等 pending_orders 累積 20+ 筆後跑 `run_pnl_tracker.py`

---

## 常見操作指令

```powershell
# 切到專案目錄（必須先做）
cd C:\Users\lenov\Desktop\polytest_trading_bot\polytest

# 手動跑一次 pipeline（需接手機熱點）
python -m scripts.run_pipeline

# 智慧鯨魚發現（需接手機熱點）
python -m scripts.run_smart_discovery

# 查 USDC 餘額
python -m scripts.check_balance

# 看訊號統計
python -m scripts._signals_stats

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
| GHA discovery 清空 whales.json | 已改用 run_smart_discovery.py |
| TG Bot Token 失效 | 由 Koh 在 BotFather 重新取得，更新 .env 和 GitHub Secrets |

---

## 何時需要升級到 Claude 4.8（Opus）

目前任務（代碼修改、資料分析、Debug）完全在 4.6 能力範圍內，**不需要升級**。

考慮升級的情況：
- 需要從零設計全新交易策略（複雜多步推理）
- 需要同時分析數千行代碼做架構審查
- 任務需要超長上下文窗口

如果遇到上述情況，Koh 手動切換即可。
