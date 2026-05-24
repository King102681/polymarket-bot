import os, requests

BOT_TOKEN = os.getenv("BOT_TOKEN", "8277515104:AAHyq3Bl7-brRjNhIPdHr8tSiW1N04wB5aI")
CHAT_ID = os.getenv("CHAT_ID", "7646956557")
MESSAGE = "【系統回報】你的 Polymarket 交易機器人已上線！"

if not BOT_TOKEN or not CHAT_ID:
    raise ValueError("BOT_TOKEN 或 CHAT_ID 未設定，請設環境變數或寫在程式裡。")

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
payload = {
    "chat_id": CHAT_ID,
    "text": MESSAGE,
    "parse_mode": "HTML"
}

try:
    response = requests.post(url, json=payload, timeout=10)
    response.raise_for_status()
    data = response.json()
    if data.get("ok"):
        print("推播成功！快去看你的手機 Telegram。")
    else:
        print("推播失敗：", data)
except requests.exceptions.RequestException as e:
    print("HTTP 請求失敗：", e)
except ValueError:
    print("回傳非 JSON，請檢查 Bot Token / Chat ID / API 回應。")