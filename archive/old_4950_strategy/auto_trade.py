import os
import time
import json
import requests
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs

# 1. 載入保險箱
load_dotenv()
PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY")
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
CHAT_ID = os.getenv("TG_CHAT_ID")

# 2. ⚡ 核心設定 (老闆控制面板) ⚡
# LIVE_MODE = False (模擬模式，不會花錢) | True (實彈模式，真的會扣 USDC)
LIVE_MODE = True
# 每次套利願意動用的總資金 (例如 10 USDC)
TRADE_AMOUNT = 10 
# 套利啟動條件 (建議設 0.985，測試可改 1.01)
PROFIT_THRESHOLD = 0.985

# 3. 初始化 Polymarket 官方下單客戶端
client = ClobClient(
    host="https://clob.polymarket.com",
    key=PRIVATE_KEY,
    chain_id=137
)
# 載入你的專屬 API 金鑰
client.set_api_creds(client.create_or_derive_api_creds())

def send_tg(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", 
                      json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=5)
    except:
        pass

def execute_arbitrage(title, yes_id, no_id, yes_price, no_price):
    print(f"\n⚡ 準備執行雙邊套利下單！")
    
    # 🎯 【數學升級：完美對沖】我們必須買「一樣多」的份額，才能保證不管誰贏都拿一樣的錢
    total_cost_per_share = yes_price + no_price
    target_shares = round(TRADE_AMOUNT / total_cost_per_share, 2)
    
    yes_size = target_shares
    no_size = target_shares
    
    # 📊 計算這筆交易的真實財務數據
    total_cost = round(target_shares * yes_price + target_shares * no_price, 2)
    guaranteed_payout = round(target_shares * 1.0, 2) # 不管誰贏，1 份就是退 1 USDC
    estimated_profit = round(guaranteed_payout - total_cost, 4)

    print(f"🛒 目標: 買 {yes_size} 份 Yes, 買 {no_size} 份 No")
    print(f"💰 總成本: {total_cost} USDC | 🏆 保證獎金: {guaranteed_payout} USDC")
    print(f"📈 預估淨利潤: +{estimated_profit} USDC")

    if not LIVE_MODE:
        msg = (
            f"🛡️ <b>【模擬下單成功】</b>\n"
            f"📌 <i>{title}</i>\n"
            f"💵 投入成本: {total_cost} USDC\n"
            f"✨ 預估淨賺: <b>+{estimated_profit} USDC</b>"
        )
        print(msg)
        send_tg(msg)
        
        # 📝 建立虛擬記帳本：把模擬的戰績寫進一個文字檔裡
        with open("sim_pnl_log.txt", "a", encoding="utf-8") as f:
            log_time = time.strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"[{log_time}] {title} | 成本: {total_cost} USDC | 淨利潤: +{estimated_profit} USDC\n")
            
        return

    # --- 💥 實彈射擊區間 (保持不變) 💥 ---
    try:
        print("🔥 正在送出 Yes 訂單...")
        yes_order = client.create_and_post_order(OrderArgs(
            price=yes_price, size=yes_size, side="BUY", token_id=yes_id
        ))
        
        print("🔥 正在送出 No 訂單...")
        no_order = client.create_and_post_order(OrderArgs(
            price=no_price, size=no_size, side="BUY", token_id=no_id
        ))
        
        msg = f"✅ <b>【實彈套利成功！】</b>\n已買入: <i>{title}</i>\n投入: {total_cost} | 預估淨賺: +{estimated_profit}\n坐等比賽結束收錢！💸"
        print(msg)
        send_tg(msg)
        
    except Exception as e:
        error_msg = f"❌ 下單失敗: {e}"
        print(error_msg)
        send_tg(error_msg)

def run_bot():
    url = "https://gamma-api.polymarket.com/events?limit=20&active=true&closed=false&sortBy=volume"
    print(f"🦞 龍蝦套利終極版已上線！(目前狀態: {'🔴 實彈模式' if LIVE_MODE else '🟢 安全模擬模式'})")
    send_tg(f"🦞 <b>系統啟動</b>: 龍蝦套利終極版已上線！\n狀態: {'🔴 實彈' if LIVE_MODE else '🟢 模擬'}")
    
    while True:
        try:
            events = requests.get(url, timeout=10).json()
            for event in events:
                title = event.get('title')
                for market in event.get('markets', []):
                    prices = market.get('outcomePrices')
                    token_ids = market.get('clobTokenIds') # 抓取下單必須的商品 ID
                    
                    if isinstance(prices, str):
                        prices = json.loads(prices)
                    
                    if isinstance(prices, list) and len(prices) >= 2 and token_ids and len(token_ids) >= 2:
                        try:
                            yes_p, no_p = float(prices[0]), float(prices[1])
                            yes_id, no_id = token_ids[0], token_ids[1]
                            
                            if (yes_p + no_p) < PROFIT_THRESHOLD and yes_p > 0 and no_p > 0:
                                execute_arbitrage(title, yes_id, no_id, yes_p, no_p)
                                time.sleep(10) # 觸發後休息 10 秒，避免重複下單
                                
                        except ValueError:
                            continue
        except Exception as e:
            print(f"掃描錯誤: {e}")
            
        time.sleep(15)

if __name__ == "__main__":
    run_bot()