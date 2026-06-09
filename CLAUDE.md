# Polymarket Whale Copy Trading Bot — 專案上下文

## 🔧 每次開始前：先選 Model（Koh 固定要求）
**每個新環節 / 新任務開始時，Claude 要先評估複雜度、明確建議用 4.6 還是 4.8，並提醒 Koh 用 `/model` 確認後再動工。**
- **4.6（sonnet，預設、省成本）**：討論、決策、debug、中小型腳本、資料分析、一般修改
- **4.8（opus）**：從零設計複雜策略、大規模架構審查、需長鏈條多步推理的工程
- ⚠️ 這是**軟性規則**（靠 Claude 每次讀 CLAUDE.md 遵守），不是系統強制彈窗。Claude Code 無「每次自動彈 model 選單」的原生功能，故用此 md 規則替代。

## ⚠️ 安全守則（絕對不能違反）
- **任何真實交易前**，必須先有 dry-run 模式驗證，且讓 Koh 明確確認後才能切換 LIVE_MODE=true
- 私鑰只放在 `~/.polymarket/.env`，絕對不能 hardcode 或 commit
- `.gitignore` 已排除 `.env*` 和 `data/backtest/`
- `LIVE_MODE` 目前在 `.github/workflows/pipeline.yml` 裡寫死為 `false`

## 🚧 地理封鎖（2026-06-09 重大發現，根本約束）
- **Polymarket 對「下單」做伺服器端 IP 地理封鎖**，與 ISP 的 DNS 攔截是兩層不同的牆。
- **台灣 = close-only**：可平倉，**不能開新倉**。Koh 人在台灣，本地 `post_order` 實測回 **403 Trading restricted**。
- `dns_patch.py` 只繞過 ISP 的 DNS RPZ（讓你能「連上」讀資料），**繞不過** Polymarket 的合規封鎖。
- **美國 2025-11 起 CFTC 合法** → GitHub Actions（美國 IP）**可能**可下單，但需實測（`verify_order.yml`）。
- **風險**：用 GHA 美國 IP = 地理規避。Polymarket 偵測超越 IP（行為/鏈上/KYC），有「提款被凍真實案例」。
  - 緩解：錢包是 **non-custodial EOA**（私鑰自控），閒置 USDC 凍不了、可鏈上轉走；只有「交易中資金」有提款被凍風險。
  - Koh 決定：**分離錢包（先轉走多數資金）+ 先用 $1 不成交驗證單試 GHA**，再決定是否放 $20。

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

## 當前鯨魚池（data/whales.json，2026-06-09 = 7 隻）

| pseudonym | proxy_wallet | 備注 |
|-----------|-------------|------|
| swisstony | 0x204f72f35326db9321... | 綜合運動賭客；足球 edge +6~9%（大單） |
| The Spirit of Ukraine>UMA | 0x0c0e270cf879583d6a... | 政治/地緣；ROI 4.3% |
| Soft-Lantern | 0xdf17f4a8dd01a4cfa6... | 高量低 ROI 0.4%；7d 僅 1 訊號，幾乎無用 |
| strike123 | 0xf284ad6d607f777f34... | GHA discovery 自動加入；sports 66% |
| Countryside | 0xbddf61af533ff524d2... | ⚠️ **在黑名單卻被 GHA 加回**，待清理 |
| **beachboy4** | 0xc2e7800b5af46e6093... | ⚽**狙擊手型** edge **+21%**；一天挑1場重倉勝負盤；但 value 僅 $5k（資金已撤）、樣本僅 12 場 |
| **RN1** | 0x2005d16a84ceefa912... | ⚽撒網型；整體 edge +3% 但大單 edge **+11.8%**；value $134k 活躍 |

### ⚽ 足球鯨魚回測核心結論（2026-06-09）
- **判斷「常勝隊有沒有說法」用 EDGE = 實際勝率 − 平均進場價**（市場隱含勝率）。
  - edge > 0 = 真 alpha（選對被低估的隊）；edge ≈ 0 = 只是跟賠率，跟單無意義。
- **規律**：越選擇性（一天挑1場）→ edge 越大；越全押（一天7場）→ edge 趨近 0。
- **跟單黃金公式：勝率 ÷ 進場價**（>1 且越大越賺）。進場價越低 + edge 越大 = 跟單越賺。
  - swisstony 超大單押超熱門（進場價 0.83）→ 跟單 ROI **−8%**（賠率太差）。
  - beachboy4（進場價 0.64）→ 跟單 ROI **+35%**；RN1（0.74）→ **+27%**。
- **工具**：`scripts/run_soccer_backtest.py`（edge + 入場頻率）、`run_soccer_discovery.py`（找足球鯨魚）。

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

## 待辦清單（2026-06-09 更新）

### 🔴 LIVE 可行性（卡在地理封鎖）
1. **看 GHA `verify_order.yml` 結果**：美國 IP 能否 `post_order`？
   - ✅ 拿到 order_id → GHA 路線可行 → 分離錢包 + 放 $20 跟世界盃
   - ❌ 403 → 美國也被擋 → 需日本 VPS 或放棄真錢、只做訊號
2. **LIVE 技術前提已驗證**：USDC approve 已做（$100萬）、簽名鏈路通過、executor import 已修（0.34.6）。**唯一瓶頸是地理封鎖**。
3. **若放 $20**：先把多數 USDC 轉到乾淨錢包（non-custodial 保護），下單錢包只留小額。

### 🟡 策略 / 清理
4. **清 Countryside**：它在 WHALE_BLACKLIST 卻被 GHA discovery 加回 whales.json，且 discovery 會覆蓋。需修 discovery 尊重黑名單。
5. **soccer 策略**（dry-run 中）：跟 beachboy4/RN1/swisstony 足球單，價格甜區 0.55-0.80，小注 follow_ratio=0.004 cap $3。等世界盃（6/11）有足球市場才會出訊號。
6. **世界盃 6/11 開賽**：soccer 策略 + TrendRader 都會受益。

### 📁 本次新增檔案
- `whale_copy/sport_classifier.py`：細分 soccer/tennis/baseball/basketball（世界盃策略用）
- `scripts/run_soccer_backtest.py` / `run_soccer_discovery.py`：足球 edge 分析 + 鯨魚發現
- `scripts/check_clob_auth.py` / `check_live_readiness.py` / `verify_live_order.py`：LIVE 就緒度與下單驗證
- `.github/workflows/verify_order.yml`：GHA 美國 IP 下單驗證（手動觸發）

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
