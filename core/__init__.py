"""import core 時做兩件事：
1. Windows cp1252 → UTF-8 重設，讓 print 中文/emoji 不炸
2. 啟用 DNS bypass，繞過本機 ISP 對 polymarket.com 的攔截
"""
import sys

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

from . import dns_patch
dns_patch.install(refresh=True)
