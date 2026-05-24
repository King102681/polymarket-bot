"""診斷 SSL 自簽憑證錯誤：抓出實際送來的憑證 issuer，定位攔截源頭。

若 issuer 不是 Let's Encrypt / Cloudflare / Google Trust，則本機有 SSL inspection。
"""
import socket
import ssl
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core  # noqa  # 載入 UTF-8 reconfig

TARGETS = [
    "gamma-api.polymarket.com",
    "clob.polymarket.com",
    "data-api.polymarket.com",
    "1rpc.io",
    "polygon-rpc.com",
]


def probe(host: str) -> None:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, 443), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert_der = ssock.getpeercert(binary_form=True)
                cert_pem = ssl.DER_cert_to_PEM_cert(cert_der)
                # 用 cryptography 解析（或內建簡單）
                try:
                    from cryptography import x509
                    from cryptography.hazmat.backends import default_backend
                    cert = x509.load_pem_x509_certificate(cert_pem.encode(), default_backend())
                    issuer = cert.issuer.rfc4514_string()
                    subject = cert.subject.rfc4514_string()
                    print(f"{host}")
                    print(f"  issuer : {issuer}")
                    print(f"  subject: {subject}")
                except ImportError:
                    print(f"{host}: 拿到憑證但缺 cryptography 套件解析 (pip install cryptography)")
                    print(cert_pem.splitlines()[0])
    except Exception as e:
        print(f"{host}: ❌ 連線失敗: {type(e).__name__}: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print(" SSL Certificate Diagnosis")
    print("=" * 60)
    print("解讀：")
    print("  - 正常 issuer 應該是 Let's Encrypt / Cloudflare / Google Trust 等公開 CA")
    print("  - 若 issuer 是「Kaspersky」「ESET」「Avast」「BitDefender」等防毒名")
    print("    → 本機防毒做 SSL inspection，需在防毒設定關閉")
    print("  - 若 issuer 是公司名 / 路由器名 → 網路層 firewall 做 SSL inspection")
    print()
    for host in TARGETS:
        probe(host)
        print()
