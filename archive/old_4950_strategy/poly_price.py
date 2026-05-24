import os
from dotenv import load_dotenv
import requests

# 1. 紀律：第一步永遠是載入保險箱 (即使這次只是讀取公開報價，也要養成習慣)
load_dotenv()

print("📡 正在向 Polymarket 伺服器發送請求，請稍候...")

# 2. 定義目標：這是 Polymarket 的公開 API 網址 
# 參數意思是：只要 1 筆資料 (limit=1)、必須是進行中的事件 (active=true)、按交易量排序 (sortBy=volume)
url = "https://gamma-api.polymarket.com/events?limit=1&active=true&closed=false&sortBy=volume"

# 3. 執行動作：派你的跑腿小弟 (requests) 去把資料拿回來
response = requests.get(url)

# 4. 判斷邏輯：檢查伺服器有沒有給你吃閉門羹 (HTTP 狀態碼 200 代表成功)
if response.status_code == 200:
    # 將拿回來的一大坨原始數據，轉換成 Python 看得懂的 JSON (列表與字典)
    data = response.json()
    
    # 剝洋蔥：進入第一筆資料 [0]，並把標題 "title" 抽出來
    event_title = data[0]["title"]
    
    print("-----------------------------------")
    print("✅ 連線成功！你的程式已經可以看懂市場了。")
    print(f"🔥 目前 Polymarket 全網交易量最高的事件是：\n【 {event_title} 】")
    print("-----------------------------------")
else:
    print(f"❌ 連線失敗！伺服器回應代碼：{response.status_code}")