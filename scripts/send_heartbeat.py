"""每日心跳：證明系統還活著，跟主 pipeline 的訊號內容無關。

主 pipeline（run_pipeline.py / run_trend_pipeline.py）只有「真的有訂單」才推播 TG，
0 單時故意沉默（避免洗版）。這導致「系統安靜因為沒單」跟「系統悄悄壞掉」看起來一樣。

這支腳本獨立排程（heartbeat.yml），每天固定送一則訊息，回報每個策略目前累計
拒絕筆數 + 資料檔最後更新時間 + 待執行訂單數。重點不是訊號內容，是「這則訊息
本身有沒有準時出現」——沒收到才代表 GHA / repo / secrets 出問題。

執行：python -m scripts.send_heartbeat
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core  # noqa  DNS patch + UTF-8

import requests

from core import config

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# (顯示名稱, rejected檔名)；pending檔名由 rejected_ 自動推導
_STRATEGIES = [
    ("🗳️ political",   "rejected_political.jsonl"),
    ("🎾 sports_live",  "rejected_sports_live.jsonl"),
    ("⚽ soccer",        "rejected_soccer.jsonl"),
    ("🔍 open",          "rejected_open.jsonl"),
    ("🌊 trend",         "rejected_trend.jsonl"),
]


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with open(path, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def _age_str(path: Path) -> str:
    if not path.exists():
        return "從未"
    age_sec = time.time() - path.stat().st_mtime
    if age_sec < 3600:
        return f"{age_sec / 60:.0f}分鐘前"
    if age_sec < 86400:
        return f"{age_sec / 3600:.1f}小時前"
    return f"{age_sec / 86400:.1f}天前"


def build_report() -> str:
    ts = time.strftime("%Y-%m-%d %H:%M")
    lines = [
        "📡 <b>每日心跳檢查</b>",
        f"   {ts}",
        "━━━━━━━━━━━━━━━━━━━",
        "（這則訊息本身就是重點：沒收到才代表系統出問題）",
        "",
    ]
    for label, rejected_name in _STRATEGIES:
        rej_path = _DATA_DIR / rejected_name
        pending_name = rejected_name.replace("rejected_", "pending_orders_")
        pending_path = _DATA_DIR / pending_name

        rej_count = _line_count(rej_path)
        pending_count = _line_count(pending_path)
        age = _age_str(rej_path)

        flag = "⭐" if pending_count > 0 else ""
        lines.append(
            f"{label}：累計拒絕 {rej_count} 筆（{age}更新）"
            f"｜待執行 {pending_count} 筆{flag}"
        )

    return "\n".join(lines)


def send_telegram(text: str) -> bool:
    if not config.TG_BOT_TOKEN or not config.TG_CHAT_ID:
        print("⚠️ TG_BOT_TOKEN 或 TG_CHAT_ID 未設定，跳過推送")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{config.TG_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": config.TG_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        return r.ok
    except Exception as e:
        print(f"⚠️ TG 推送失敗: {e}")
        return False


def main() -> None:
    report = build_report()
    print(report)
    ok = send_telegram(report)
    print(f"\n{'✅ 已推送' if ok else '❌ 推送失敗'}")


if __name__ == "__main__":
    main()
