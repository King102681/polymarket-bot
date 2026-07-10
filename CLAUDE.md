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
- **✅ 已實測（2026-07-09）：GHA（Azure 美國 IP）POST /order 被拒**——`RequestRejectedError: Trading restricted in your region`。認證、找市場、簽名全部成功，唯獨送單那一刻被擋，跟「唯讀API不受封鎖」的已知模式一致。**推論：封鎖很可能不只看國別，額外連雲端/資料中心IP網段一起擋**（業界防規避常見做法）——這代表「Canada VPS」備案大機率碰到同樣問題（AWS/Azure/GCP/DigitalOcean 等雲端商的IP不論開在哪一國都可能被連坐）。真正可能有效的只剩**住宅出口 VPN/代理**，但這是比「剛好用雲端伺服器」更明確的主動規避行為，風險評估要相應調高。
- **風險**：用 GHA 美國 IP = 地理規避。Polymarket 偵測超越 IP（行為/鏈上/KYC），有「提款被凍真實案例」。
  - 緩解：錢包是 **non-custodial EOA**（私鑰自控），閒置 USDC 凍不了、可鏈上轉走；只有「交易中資金」有提款被凍風險。
  - Koh 決定：**分離錢包（先轉走多數資金）+ 先用 $1 不成交驗證單試 GHA**，再決定是否放 $20。

---

## 專案概覽
**兩條獨立策略，平行運作**：
- **策略A（鯨魚跟單）**：跟單 Polymarket 高獲利鯨魚，依策略各自的 follow_ratio 縮小金額跟單
- **策略B（TrendRadar×Gemini）**：抓社媒熱門話題，LLM 判斷方向與信心，自動產生下單建議

**部署**：GitHub Actions 全自動，4 個 workflow（見下方「GHA Workflows」），狀態檔 commit 回 repo。

**根目錄**：`C:\Users\lenov\Desktop\polytest_trading_bot\polytest\`

**GitHub**：`https://github.com/King102681/polymarket-bot`

---

## GHA Workflows

| Workflow | 排程 | 用途 |
|----------|------|------|
| `pipeline.yml` | 每 5 分鐘 | 策略A主迴圈：monitor → signal_generator(4策略) → executor → TG |
| `trend_pipeline.yml` | 每 10 分鐘 | 策略B主迴圈：抓趨勢 → 配對市場 → Gemini評估 → 下單建議 |
| `discovery.yml` | 每週一 00:00 UTC | 智慧鯨魚發現，自動更新 whales.json |
| `verify_order.yml` | 手動觸發 | 美國 IP 下單能力驗證（$1 不成交單） |

---

## 模組結構

```
core/
  config.py            讀取 ~/.polymarket/.env 所有設定
  polymarket_client.py Gamma/CLOB/Data API 封裝
  dns_patch.py         繞過 ISP DNS 攔截（家中 ISP 封鎖 *.polymarket.com）

whale_copy/                ── 策略A：鯨魚跟單 ──
  discovery.py         從排行榜找高獲利鯨魚（基礎版）
  strategies.py        ★ 多策略設定（StrategyConfig）：political/sports_live/soccer/open
  monitor.py           掃描鯨魚新交易 → data/signals.jsonl
  signal_generator.py  process_all(strategy) 過濾 signal → data/pending_orders_{strategy}.jsonl
  executor.py          執行下單（目前 dry-run）
  market_classifier.py 市場分類 sports / crypto / politics / other
  sport_classifier.py  細分 soccer/tennis/baseball/basketball（世界盃用）

trend_trade/                ── 策略B：TrendRadar × Gemini ──
  trend_fetcher.py      抓 TrendRadar headless 熱門話題 + external_sources RSS
  external_sources.py   英文政治/地緣 RSS 補充源
  market_matcher.py     中文話題 → 英文關鍵字 → Gamma search 配對候選市場
  signal_evaluator.py   呼叫 LLM 評估（選市場+方向+信心）→ pending_orders_trend.jsonl
  llm.py                雙供應商：Gemini（免費，預設）/ Anthropic Claude（備用）

backtest/
  pull_historical.py   拉鯨魚歷史 BUY trades + 市場結算狀態
  simulator.py         模擬跟單邏輯，計算 PnL
  analyzer.py          輸出回測報告（IS/OOS 分析）
  fees.py              手續費常數（taker 0.20%）

scripts/
  run_pipeline.py        ★ 策略A主入口：對 STRATEGIES 裡每個策略跑 process_all
  run_trend_pipeline.py  ★ 策略B主入口：trend_fetcher → market_matcher → signal_evaluator
  run_smart_discovery.py ★ 智慧鯨魚發現（篩 other≥25% 且 0.20-0.80 價格比例≥20%）
  run_soccer_backtest.py   足球專項 edge 回測（評估是否該把鯨魚加入 soccer 策略）
  run_soccer_discovery.py  找足球鯨魚
  run_backtest.py          手動跑完整回測
  run_pnl_tracker.py       追蹤 dry-run 訂單前向 PnL
  check_balance.py         查錢包 USDC 餘額
  check_config.py          確認 .env 設定正確
  generate_api_keys.py     產生 Polymarket CLOB API Key
```

---

## 策略A：多策略系統（whale_copy/strategies.py）

四個策略獨立運行，各自輸出 `data/{pending_orders,rejected,processed}_{name}.{jsonl,json}`：

| 策略 | whale_filter | min_size | price 區間 | 備註 |
|------|-------------|----------|-----------|------|
| **political** | 全部（非黑名單） | $100 | 0.20–0.87 | 長期政治/地緣；7天以上才跟 |
| **sports_live** | swisstony 限定 | $500 | 0.70–0.97 | 網球直播大單，允許當日賽事 |
| **soccer** | beachboy4/RN1/swisstony | $100 | 0.55–0.80 | 世界盃狙擊，甜區避開超熱門；follow_ratio=0.004, cap $3 |
| **open** | 全部 | $50 | 0.15–0.95 | 低門檻開放探索，無類別過濾，純收集數據 |

全策略共用黑名單 `WHALE_BLACKLIST`（`whale_copy/signal_generator.py`）：
```python
WHALE_BLACKLIST = {"0xbddf61af533ff524d27154e589d2d7a81510c684"}  # Countryside（回測虧損）
```

**重要**：要把新鯨魚加進 `soccer` 策略前，**先跑 `run_soccer_backtest.py <wallet>` 驗證 edge 是否為正**——
高利潤≠足球選股能力（見下方鯨魚池「已評估未採用」）。

---

## 策略B：TrendRadar × Gemini（trend_trade/）

**核心假設**：社媒熱度領先市場定價 30–120 分鐘。

**流程**：抓熱門話題（熱度≥40）→ 關鍵字配對 Polymarket 候選市場（Top-5流動性）→ Gemini 選市場+判方向(YES/NO/NONE)+給信心 → 信心≥門檻才產生訂單建議。

**關鍵設定**（`core/config.py` + `trend_pipeline.yml` 覆寫）：
```
TREND_MIN_HEAT=40            # 熱度門檻
TREND_MIN_CONFIDENCE=0.35    # 信心門檻（0.55→0.45→0.35；dry-run 刻意調低收集樣本，
                             # 每筆訂單記錄自己的 confidence，結算後分區間算勝率/edge，
                             # 上 LIVE 前用數據決定真正的門檻——不是憑感覺猜）
TREND_MIN_HOURS_LEFT=48      # 距結算 < 48h 不下
TREND_MIN_ENTRY_PRICE=0.10 / TREND_MAX_ENTRY_PRICE=0.90
GEMINI_API_KEY               # 免費版優先；ANTHROPIC_API_KEY 備用
```

**Gemini 安全過濾已關閉**（2026-06-19）：地緣政治/軍事新聞是核心輸入，預設安全過濾會把 Iran/Israel 等
合法財經分析判定為 DANGEROUS_CONTENT 擋掉。`llm.py` 的 `_call_gemini` 已加 `safetySettings: BLOCK_NONE`。

**market_matcher.py 關鍵字表**：中文新聞常見「縮寫」（美伊/俄军/乌军/对台/涉台）不含完整國名子字串，
要單獨列出才能配到。2026-06-19 分析 217 條趨勢，配對率 37%→47%。新增話題類型時，先用這個腳本檢查覆蓋率：
```python
from trend_trade.market_matcher import _find_query
# 對 data/trend_state.json 的 key 逐一跑 _find_query()，看哪些回 None
```

**已知瓶頸**：新聞被 TrendRadar 抓到時，對應市場常已定價到 0.99+（例如美伊協議簽署當下）。
30–120 分鐘領先假設在「已塵埃落定」的新聞上不成立，需等真正的突發/反轉事件。

---

## 關鍵設定（pipeline.yml / .env，全域預設值）

```
LIVE_MODE=false          # ← 上 live 前改成 true（需 Koh 明確確認）
MAX_BET_USDC=10          # 單筆上限（全域預設，soccer 策略覆寫成 $3）
MAX_TOTAL_OPEN_USDC=100  # 總開倉上限
WHALE_FOLLOW_RATIO=0.001 # 跟單比例預設值（各策略可覆寫）
INITIAL_CAPITAL_USDC=100 # 初始資金（記錄用）
```

---

## 當前鯨魚池（data/whales.json，2026-06-19 = 8 隻）

| pseudonym | proxy_wallet | ROI 30d | sports% | 備注 |
|-----------|-------------|---------|---------|------|
| swisstony | 0x204f72f35326db93... | 6.9% | 50% | 綜合運動賭客；足球 edge +6~9%（大單） |
| The Spirit of Ukraine>UMA | 0x0c0e270cf879583d... | 4.3% | 0% | 政治/地緣 |
| Soft-Lantern | 0xdf17f4a8dd01a4cf... | 0.4% | 2% | 高量低 ROI，幾乎無用 |
| strike123 | 0xf284ad6d607f777f... | 2.0% | 66% | GHA discovery 自動加入 |
| **beachboy4** | 0xc2e7800b5af46e60... | 2.1% | 76% | ⚽soccer策略；狙擊手型 edge **+21%** |
| **RN1** | 0x2005d16a84ceefa9... | 2.1% | 47% | ⚽soccer策略；撒網型，大單 edge **+11.8%** |
| GoalLineGhost | 0x0346afae2603313d... | 5.8% | 28% | discovery 自動加入；**足球 edge 已驗證為負，未加入 soccer 策略**（見下） |
| (匿名地址) | 0x2c335066fe58fe92... | 2.7% | 44% | discovery 自動加入，尚未評估 |

**Countryside 已移除**（黑名單 + discovery 合併邏輯已修正尊重黑名單，2026-06）

### ⚽ 足球鯨魚回測核心結論
- **判斷「常勝隊有沒有說法」用 EDGE = 實際勝率 − 平均進場價**（市場隱含勝率）。
  - edge > 0 = 真 alpha（選對被低估的隊）；edge ≈ 0 或 < 0 = 跟單無意義甚至虧錢。
- **規律**：越選擇性（一天挑1場）→ edge 越大；越全押 → edge 趨近 0 甚至負。
- **跟單黃金公式：勝率 ÷ 進場價**（>1 且越大越賺）。
  - beachboy4（進場價 0.64）→ 跟單 ROI **+35%**；RN1（0.74）→ **+27%**。
  - swisstony 超大單押超熱門（進場價 0.83）→ 跟單 ROI **−8%**（賠率太差）。

### ✅ 已評估未採用：GoalLineGhost（2026-06-19）
表面數據誘人（30d 利潤 $1.42M、量 $24.3M），但足球專項回測：
- 全部足球 edge **-9.3%**（勝率45.4% vs 進場價54.7%）、大單 edge **-13.0%**
- 跟單模擬 ROI **-21.5%**（會虧錢）
- 大單覆蓋場次比 90%——幾乎每場都押，無選股能力，他的利潤來自其他類別（sports僅佔28%）
**結論：高利潤鯨魚不代表足球有 alpha，必須分類別回測才能用。**

**鯨魚發現邏輯（run_smart_discovery.py）**：
- Leaderboard 30d profit + volume 各抓 500 筆
- 門檻：profit ≥ $3k，volume ≥ $15k，value_now ≥ $3k
- 額外篩選：other 類別 ≥ 25%，且 other 交易中 0.20-0.80 價格比例 ≥ 20%
- 自動更新 whales.json（找到 ≥ 2 隻新鯨魚時，且尊重 WHALE_BLACKLIST）

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

## 資料檔案狀態（2026-06-19）

策略A 與策略B 各自獨立檔案，策略A 內部再依 4 個策略分別命名：

| 檔案模式 | 說明 |
|------|------|
| `data/signals.jsonl` | 策略A raw 訊號（whale monitor 輸出，全策略共用） |
| `data/pending_orders_{political,sports_live,soccer,open}.jsonl` | 策略A 各策略通過訂單；**目前 4 個全為空**（dry-run 至今 0 筆） |
| `data/rejected_{political,sports_live,soccer,open}.jsonl` | 策略A 各策略拒絕記錄 + 原因 |
| `data/processed_{political,sports_live,soccer,open}.json` | 策略A 各策略已處理 hash |
| `data/pending_orders_trend.jsonl` | 策略B 通過訂單；**目前為空** |
| `data/rejected_trend.jsonl` | 策略B 拒絕記錄（信心不足/安全過濾/LLM判不下注/價格不在範圍） |
| `data/processed_trend.json` | 策略B 已處理趨勢 hash（去重，避免重複呼叫 LLM） |
| `data/trend_state.json` | 策略B 趨勢追蹤狀態（first_seen, best_rank） |
| `data/whales.json` / `whales_smart.json` | 鯨魚池 / smart discovery 輸出 |
| `data/backtest/soccer_backtest.json` | 足球 edge 回測報告（run_soccer_backtest.py 輸出） |
| `data/signals.jsonl`（舊）/ `pending_orders.jsonl`（舊） | **已棄用**，多策略改版前的全域檔案，不再寫入 |

---

## 待辦清單（2026-06-19 更新）

### 🔴 LIVE 可行性（2026-07-09 已實測，GHA 路線確認不可行）
1. **`verify_order.yml` 結果已出**：❌ Azure 美國 IP 被拒（`Trading restricted in your region`）。GHA 路線死路，且推論 Canada VPS 等雲端方案大機率同樣被擋（見上方地理封鎖章節的推論）。**唯一剩下可能有效的是住宅出口 VPN/代理，但規避意圖更明確、風險更高，需 Koh 重新評估是否值得繼續追這條路，還是接受 LIVE 對他不可行、只做 dry-run 訊號驗證。**
2. **LIVE 技術前提已驗證**：USDC approve 已做、簽名鏈路通過。**唯一瓶頸是地理封鎖**（現已證實比原先設想的更廣，非僅國別判斷）。
3. **決策原則（Koh 2026-06）**：先用 dry-run 證明策略賺錢，才決定是否付費上 VPS。

   **「證明賺錢」的具體門檻（2026-06-22 定案，三個條件同時滿足才算）**：
   - 樣本量：≥30 筆**已結算**交易（pending 不算，要真的 win/lose 結算）
   - 報酬率：整體已結算 ROI ≥ +15%（回測 political +27~30%、soccer edge鯨魚 +21~27%；
     15% 是打折後還有賺的底線，連這個都做不到代表抓單時機/滑價問題比想像中嚴重）
   - 時間跨度：連續運行 ≥4 週（避免單一週運氣干擾判斷）

   **成本效益另算**：`MAX_BET_USDC=10`、soccer cap $3，現在的測試金額算出來的月獲利
   可能蓋不過 VPS 月費。上 LIVE 前記得同步調大單筆上限，不要用 dry-run 的測試金額
   去判斷「值不值得付費上 VPS」。

### 🟡 策略B（TrendRadar）持續調優
4. **觀察新關鍵字擴充後的配對率**：2026-06-19 已修「美伊/俄军/乌军/对台/涉台」等縮寫覆蓋缺口，配對率 37%→47%，待下輪 GHA 驗證實際 pending order 是否出現。
5. **等真正突發事件**：目前新聞（美伊協議）多已塵埃落定，市場價格 0.99+，30-120分鐘領先假設不適用；需等下一個還沒被定價的事件。

### 🟢 策略A 鯨魚池維護
6. **新發現鯨魚評估**：匿名地址 `0x2c335066...`（ROI 2.7%, sports 44%）尚未做足球專項回測，暫不加入 soccer whale_filter。
7. **GoalLineGhost 已確認不適合 soccer 策略**（edge -9%~-13%），維持只在 political/open 策略下生效。

---

## 常見操作指令

```powershell
# 切到專案目錄（必須先做）
cd C:\Users\lenov\Desktop\polytest_trading_bot\polytest

# 手動跑一次策略A pipeline（需接手機熱點）
python -m scripts.run_pipeline

# 手動跑一次策略B trend pipeline
python -m scripts.run_trend_pipeline

# 智慧鯨魚發現（需接手機熱點）
python -m scripts.run_smart_discovery

# 足球專項回測（驗證是否該把鯨魚加入 soccer 策略）
python -m scripts.run_soccer_backtest <wallet_address>

# 查 USDC 餘額
python -m scripts.check_balance

# 追蹤前向 PnL（需有 pending_orders 才有數據）
python -m scripts.run_pnl_tracker
```

PowerShell 讀取 jsonl/json 資料檔記得加 `-Encoding UTF8`，否則中文會變亂碼。
SSH/Python 混用時用 here-string 管線 `$script = @'...'@; $script | ssh ... "python3 -"`，避免巢狀引號地獄。

---

## 已知問題與解法

| 問題 | 解法 |
|------|------|
| ISP 封鎖 polymarket.com | 接手機熱點再跑 |
| UnicodeEncodeError（Windows PowerShell） | 腳本開頭加 `sys.stdout.reconfigure(encoding='utf-8')` |
| git push 被拒（GHA 也在 commit） | `git pull --rebase origin main` → `git push` |
| Data API offset > 3000 回傳 400 | `_fetch_trades_page` 返回 None 時停止分頁 |
| Gamma API 找不到已關閉市場 | fallback 到 CLOB API（`_fetch_market_clob`） |
| GHA discovery 清空 whales.json | 已改用 run_smart_discovery.py |
| TG Bot Token 失效 | 由 Koh 在 BotFather 重新取得，更新 .env 和 GitHub Secrets |
| discovery 把黑名單鯨魚加回 whales.json | merge 邏輯需同時過濾 `current` 和 `new_whales`（兩處都要排除 BLACKLIST） |
| `validate_trend()` 只認 ANTHROPIC_API_KEY | 改成接受 GEMINI_API_KEY 或 ANTHROPIC_API_KEY 任一個 |
| Gemini 安全過濾擋掉地緣政治新聞 | `llm.py` 的 request body 加 `safetySettings` 全設 `BLOCK_NONE` |
| 中文新聞縮寫（美伊/俄军/对台）配不到關鍵字 | `market_matcher.py` KEYWORD_MAP 需把縮寫也列為獨立關鍵字，不能只靠完整國名子字串 |
| GHA Node.js 24 棄用警告 | 各 workflow 的 job env 加 `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true`（deadline 2026-06-16前完成） |

---

## 何時需要升級到 Claude 4.8（Opus）

目前任務（代碼修改、資料分析、Debug）完全在 4.6 能力範圍內，**不需要升級**。

考慮升級的情況：
- 需要從零設計全新交易策略（複雜多步推理）
- 需要同時分析數千行代碼做架構審查
- 任務需要超長上下文窗口

如果遇到上述情況，Koh 手動切換即可。
