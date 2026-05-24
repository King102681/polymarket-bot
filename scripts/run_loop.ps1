# Polymarket Whale Copy Pipeline — PowerShell loop
# 每 INTERVAL_SEC 秒跑一次。Ctrl+C 中止。
#
# 用法：
#   cd C:\Users\lenov\Desktop\polytest_trading_bot\polytest
#   .\scripts\run_loop.ps1
#
# 注意：電腦進入睡眠時 loop 會暫停，醒來繼續。

$ErrorActionPreference = "Continue"
$INTERVAL_SEC = 600   # 10 分鐘
$projectDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)

Set-Location $projectDir
Write-Host "Pipeline loop 啟動，每 $INTERVAL_SEC 秒跑一次" -ForegroundColor Green
Write-Host "工作目錄: $projectDir" -ForegroundColor Gray
Write-Host "Ctrl+C 中止`n" -ForegroundColor Gray

while ($true) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$ts] ── tick ──" -ForegroundColor Cyan
    try {
        python -m scripts.run_pipeline
    } catch {
        Write-Host "Pipeline 跑錯誤: $_" -ForegroundColor Red
    }
    Write-Host "sleep $INTERVAL_SEC s..." -ForegroundColor DarkGray
    Start-Sleep -Seconds $INTERVAL_SEC
}
