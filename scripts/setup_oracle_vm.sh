#!/bin/bash
# ============================================================
#  Polymarket Bot — Oracle Cloud Free Tier Ubuntu 一鍵 Setup
#  用法：ssh 進 VM 後執行
#    bash <(curl -sSf https://raw.githubusercontent.com/King102681/polymarket-bot/main/polytest/scripts/setup_oracle_vm.sh)
#  或上傳後：chmod +x setup_oracle_vm.sh && ./setup_oracle_vm.sh
# ============================================================
set -e

REPO_URL="https://github.com/King102681/polymarket-bot.git"
BOT_DIR="$HOME/polymarket-bot/polytest"
SERVICE_NAME="polymarket-bot"

echo "======================================================"
echo "  Step 1/5 — 系統更新 + 安裝 Python"
echo "======================================================"
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv git curl

echo "======================================================"
echo "  Step 2/5 — 安裝 NordVPN"
echo "======================================================"
if ! command -v nordvpn &>/dev/null; then
    sh <(curl -sSf https://downloads.nordcdn.com/apps/linux/install.sh)
    sudo usermod -aG nordvpn "$USER"
    echo ""
    echo "  ⚠️  NordVPN 已安裝，需重新登入 SSH 才能使用 nordvpn 指令"
    echo "  請執行：nordvpn login"
    echo "  複製 URL 在瀏覽器完成登入，然後再跑一次此腳本"
    echo ""
else
    echo "  NordVPN 已存在，跳過安裝"
fi

echo "======================================================"
echo "  Step 3/5 — Clone / 更新 Repo"
echo "======================================================"
if [ -d "$HOME/polymarket-bot" ]; then
    cd "$HOME/polymarket-bot" && git pull origin main
else
    git clone "$REPO_URL" "$HOME/polymarket-bot"
fi

echo "======================================================"
echo "  Step 4/5 — 安裝 Python 相依套件"
echo "======================================================"
cd "$BOT_DIR"
pip3 install --break-system-packages -r requirements.txt

echo "======================================================"
echo "  Step 5/5 — 建立 .env 設定目錄"
echo "======================================================"
mkdir -p "$HOME/.polymarket"

if [ ! -f "$HOME/.polymarket/.env" ]; then
    cat > "$HOME/.polymarket/.env" << 'ENVTEMPLATE'
TG_BOT_TOKEN=
TG_CHAT_ID=
WALLET_PRIVATE_KEY=
POLYGON_RPC_URL=https://1rpc.io/matic

POLY_API_KEY=
POLY_API_SECRET=
POLY_API_PASSPHRASE=

LIVE_MODE=true
MAX_BET_USDC=3
MAX_TOTAL_OPEN_USDC=20
DAILY_LOSS_LIMIT_USDC=10
WHALE_FOLLOW_RATIO=0.001
INITIAL_CAPITAL_USDC=100
ENVTEMPLATE
    echo "  ⚠️  請填入 ~/.polymarket/.env 的值（私鑰 + API Key）"
fi

echo "======================================================"
echo "  建立 systemd 服務（含 VPN 自動啟動）"
echo "======================================================"
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null << SERVICEEOF
[Unit]
Description=Polymarket Whale Copy Trading Bot
After=network-online.target nordvpnd.service
Wants=network-online.target

[Service]
Type=simple
User=${USER}
WorkingDirectory=${BOT_DIR}
# 啟動前連 VPN（加拿大住宅 IP）
ExecStartPre=/bin/bash -c 'nordvpn connect Canada; sleep 8'
ExecStart=/usr/bin/python3 -m scripts.run_loop 300
# 失敗後 60 秒重試（含 VPN 重連）
Restart=always
RestartSec=60
# 環境
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONIOENCODING=utf-8

[Install]
WantedBy=multi-user.target
SERVICEEOF

sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}

echo ""
echo "======================================================"
echo "  ✅ Setup 完成！"
echo "======================================================"
echo ""
echo "  下一步："
echo "  1. nordvpn login          # 登入 NordVPN（只需做一次）"
echo "  2. nordvpn set obfuscate on"
echo "  3. nordvpn set technology openvpn"
echo "  4. nordvpn connect Canada  # 測試連線"
echo "  5. nano ~/.polymarket/.env # 填入私鑰和 API Key"
echo "  6. sudo systemctl start polymarket-bot"
echo "  7. sudo journalctl -fu polymarket-bot  # 看即時 log"
echo ""
echo "  之後重開機會自動跑，永遠不用管。"
