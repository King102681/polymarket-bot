# 部署指南

## 三種跑法擇一

### A. 本機 PowerShell loop（最簡單，需要電腦開機）

```powershell
cd C:\Users\lenov\Desktop\polytest_trading_bot\polytest
.\scripts\run_loop.ps1
```

- 每 10 分鐘跑一次 pipeline
- 電腦睡眠時暫停
- Ctrl+C 中止
- 預設 LIVE_MODE=false，不下真實單

### B. Windows Task Scheduler（電腦開機就跑）

1. 開「工作排程器」→ 建立基本工作
2. 觸發程序：每天 → 每 15 分鐘重複
3. 動作：啟動程式
   - 程式：`python`
   - 引數：`-m scripts.run_pipeline`
   - 起始於：`C:\Users\lenov\Desktop\polytest_trading_bot\polytest`
4. 選項：勾「不論使用者是否登入」+「使用最高權限」

### C. GitHub Actions cron（24/7、免費、IP 在美國繞 DNS 攔截）✨ 推薦

1. **建立 GitHub repo（私人）**：
   ```bash
   cd C:\Users\lenov\Desktop\polytest_trading_bot\polytest
   git init
   git add .
   git commit -m "initial"
   gh repo create polymarket-bot --private --source=. --push
   ```

2. **設定 Secrets**（repo Settings → Secrets and variables → Actions → New repository secret）：

   | Secret name | 值 |
   |---|---|
   | `WALLET_PRIVATE_KEY` | 你的私鑰 |
   | `POLY_API_KEY` | Polymarket API key |
   | `POLY_API_SECRET` | Polymarket API secret |
   | `POLY_API_PASSPHRASE` | Polymarket API passphrase |
   | `POLYGON_RPC_URL` | RPC URL（如 `https://1rpc.io/matic`） |
   | `TG_BOT_TOKEN` | Telegram bot token |
   | `TG_CHAT_ID` | Telegram chat id |

3. **首次手動觸發 discovery 產生 whales.json**：
   - Actions tab → "Refresh Whales (weekly)" → Run workflow
   - 之後每週一自動跑一次

4. **pipeline 開始 cron**：
   - `.github/workflows/pipeline.yml` 設定為每 30 分鐘
   - 每月用量約 1440 分鐘，免費額度 2000 分鐘 ✓
   - 訊號出現時自動推 Telegram

#### 改成每 15 分鐘？
編輯 `pipeline.yml`：
```yaml
- cron: '*/15 * * * *'
```
但每月用量 ~2880 分鐘，**超過免費額度** → 需上 GitHub Pro $4/月（3000 分鐘）。

## 切換 LIVE_MODE

⚠️ **預設 dry-run，不下真實單**。要切實彈：

### 本機：
編輯 `~/.polymarket/.env`：
```
LIVE_MODE=true
```

### GitHub Actions：
編輯 `.github/workflows/pipeline.yml` 中：
```yaml
LIVE_MODE=true
```
或更安全：把 LIVE_MODE 改成從 secret 讀，方便快速 toggle。

## 觀察與調整

訊號出現後：
- 對照 Telegram 通知與實際市場走勢
- 累積 2-4 週訊號（樣本 N=10-30 筆）後，用 backtest analyzer 風格分析實盤結果
- 與回測 IS 預期（+5% ROI）對比，看是否符合
- 若實盤表現低於 IS：可能是 DNS lag、滑點低估、或 selection bias
- 若實盤接近 IS：再考慮放大 `MAX_BET_USDC`
