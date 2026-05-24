import requests

print("📡 正在向 Polymarket 伺服器發送請求，請稍候...")

# 1. 鎖定目標：這是 Polymarket 官方提供的公開 API 網址
# 參數：limit=1 (只抓一筆), active=true (進行中), sortBy=volume (按交易量排序)
url = "https://gamma-api.polymarket.com/events?limit=1&active=true&closed=false&sortBy=volume"

# 2. 派跑腿小弟去拿資料
response = requests.get(url)

# 3. 檢查伺服器有沒有正常回應 (200 代表成功)
if response.status_code == 200:
    # 將拿回來的生肉 (文字)，煮熟成 Python 看得懂的字典 (JSON)
    data = response.json()
    
    # 4. 剝洋蔥：進入清單的第一筆資料 [0]，把標題 "title" 抽出來
    event_title = data[0]["title"]
    
    print("-----------------------------------")
    print("✅ 連線成功！你的程式已經有了視覺。")
    print(f"🔥 目前 Polymarket 全網交易量最高的事件是：\n【 {event_title} 】")
    print("-----------------------------------")
else:
    print(f"❌ 連線失敗！伺服器回應代碼：{response.status_code}")