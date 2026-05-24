import os
import requests
import time
import json
from dotenv import load_dotenv

# 1. 載入環境變數 (你的 Telegram 密碼)
load_dotenv()
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
CHAT_ID = os.getenv("TG_CHAT_ID")

# 2. Telegram 發報機
def send_telegram_message(message_text):
    if not BOT_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message_text,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"❌ TG 推播失敗: {e}")

# 3. 核心掃描大腦
def scan_arbitrage_opportunities():
    url = "https://gamma-api.polymarket.com/events?limit=20&active=true&closed=false&sortBy=volume"
    
    try:
        response = requests.get(url)
        events = response.json()
        
        for event in events:
            title = event.get('title')
            markets = event.get('markets', [])
            
            for market in markets:
                prices = market.get('outcomePrices')
                
                # 修復字串格式問題
                if isinstance(prices, str):
                    try:
                        prices = json.loads(prices)
                    except json.JSONDecodeError:
                        continue
                        
                if isinstance(prices, list) and len(prices) >= 2:
                    try:
                        yes_price = float(prices[0])
                        no_price = float(prices[1])
                        total_cost = yes_price + no_price
                        
                        # 🎯 獵物條件：總成本低於 0.985 (即保底利潤 > 1.5%)
                        if total_cost < 0.985:
                            profit_margin = (1 - total_cost) * 100
                            
                            # 組合訊息
                            msg = (
                                f"🦞 <b>【發現無風險套利機會！】</b>\n\n"
                                f"📌 <b>市場:</b> <i>{title}</i>\n"
                                f"📈 <b>Yes 價格:</b> {yes_price}\n"
                                f"📉 <b>No 價格:</b> {no_price}\n"
                                f"💰 <b>總成本:</b> {total_cost:.3f} USDC\n"
                                f"🔥 <b>預估利潤率:</b> {profit_margin:.2f}%\n"
                                f"⏱️ <b>時間:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}"
                            )
                            print("-" * 30)
                            print(f"🔥 觸發警報！發送 TG 通知中...")
                            print(msg)
                            send_telegram_message(msg)
                            print("-" * 30)
                            
                    except ValueError:
                        continue
                        
    except Exception as e:
        print(f"❌ API 請求失敗: {e}")

# 4. 無限巡邏模式
if __name__ == "__main__":
    print("🦞 龍蝦套利雷達啟動，正在全天候監控...")
    # 啟動時先發一則訊息，確認 TG 連線正常
    send_telegram_message("✅ <b>【系統啟動】</b> 龍蝦套利雷達已上線，開始 24 小時監控市場！")
    
    # 開始無限迴圈
    while True:
        scan_arbitrage_opportunities()
        # 每 15 秒掃描一次 (不要設太快，以免被 Polymarket 封鎖 IP)
        time.sleep(15)