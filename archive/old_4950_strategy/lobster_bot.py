import os
import requests
from dotenv import load_dotenv

# --- 🕵️ X光診斷區塊開始 ---
# 強制指定 .env 的絕對路徑，並檢查檔案到底存不存在
current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(current_dir, '.env')

print("-----------------------------------")
print(f"🕵️ 1. 系統正在尋找的路徑：{env_path}")
print(f"🕵️ 2. 這個路徑下真的有 .env 檔案嗎？ {os.path.exists(env_path)}")

# 載入並強制覆蓋舊變數
load_dotenv(dotenv_path=env_path, override=True)

BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
CHAT_ID = os.getenv("TG_CHAT_ID")

print(f"🕵️ 3. 抓到的 Token 長度：{'空 (None)' if not BOT_TOKEN else len(BOT_TOKEN)}")
print("-----------------------------------")
# --- 🕵️ X光診斷區塊結束 ---

# (下方保留你原本的 get_polymarket_top_event 等函數...)

# 讀取環境變數
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
CHAT_ID = os.getenv("TG_CHAT_ID")

def get_polymarket_top_event():
    print("📡 正在向 Polymarket 伺服器發送請求...")
    url = "https://gamma-api.polymarket.com/events?limit=1&active=true&closed=false&sortBy=volume"
    
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data[0]["title"]
    else:
        print(f"❌ 連線失敗！狀態碼：{response.status_code}")
        return None

def send_telegram_message(message_text):
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ 錯誤：找不到 TG_BOT_TOKEN 或 TG_CHAT_ID，請檢查 .env 檔案！")
        return
        
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message_text,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print("✅ 推播成功！快去看你的手機 Telegram。")
    except requests.exceptions.RequestException as e:
        print("❌ 推播失敗：", e)

# 🚀 程式執行起點
if __name__ == "__main__":
    print("🦞 龍蝦交易機器人啟動中...")
    
    # 1. 獲取市場資訊
    top_event = get_polymarket_top_event()
    
    # 2. 如果成功抓到資訊，就發送 Telegram
    if top_event:
        msg = f"🦞 <b>【龍蝦市場快報】</b>\n\n🔥 目前 Polymarket 全網交易量最高的事件是：\n👉 <i>{top_event}</i>"
        send_telegram_message(msg)