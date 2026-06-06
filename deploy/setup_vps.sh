#!/bin/bash
# VPS 一鍵部署腳本（Ubuntu 22.04）
# 執行方式：bash setup_vps.sh
set -e

echo "=== Polymarket Bot VPS 部署 ==="

# 1. 系統更新
apt-get update -qq && apt-get upgrade -y -qq

# 2. 安裝 Python 3.12
apt-get install -y python3.12 python3.12-venv python3-pip git

# 3. clone repo
cd /opt
git clone https://github.com/King102681/polymarket-bot.git bot
cd bot

# 4. 建立虛擬環境
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 5. 建立 .env（之後手動填入）
mkdir -p ~/.polymarket
cat > ~/.polymarket/.env <<'EOF'
WALLET_PRIVATE_KEY=
POLY_API_KEY=
POLY_API_SECRET=
POLY_API_PASSPHRASE=
POLYGON_RPC_URL=
TG_BOT_TOKEN=
TG_CHAT_ID=
LIVE_MODE=false
MAX_BET_USDC=10
MAX_TOTAL_OPEN_USDC=100
DAILY_LOSS_LIMIT_USDC=10
WHALE_FOLLOW_RATIO=0.001
INITIAL_CAPITAL_USDC=100
EOF

echo ""
echo "=== 請手動填入 ~/.polymarket/.env 的私鑰和 API key ==="
echo "    nano ~/.polymarket/.env"
