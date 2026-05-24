"""繞過本機 DNS 攔截：用 monkey-patch socket.getaddrinfo 把 Polymarket 域名
直接導到 Cloudflare 真實 IP。

不需要管理員權限、不需要 hosts 檔、不需要 VPN。只影響 Python 程式內的連線。
TLS 仍用原本的 hostname 做 SNI 與憑證驗證，故安全性不變。

啟動時嘗試透過 Cloudflare DoH (https://1.1.1.1/dns-query) 取得最新 IP，
失敗則用 fallback 寫死值。
"""
import json
import socket
import urllib.request
from typing import Optional

# 任何屬於 polymarket.com 的子域名都走 Cloudflare DoH 動態解析。
# 第一次遇到時 resolve 一次並快取，後續直接用。
_PROTECTED_SUFFIX = ".polymarket.com"
_PROTECTED_ROOT = "polymarket.com"

# Fallback IP 列表（Cloudflare 邊緣，三個子域名都共用）
_FALLBACK_IPS = ["104.18.34.205", "172.64.153.51"]

_OVERRIDE: dict[str, list[str]] = {}
_original_getaddrinfo = socket.getaddrinfo
_installed = False


def _is_protected(host: str) -> bool:
    return host == _PROTECTED_ROOT or host.endswith(_PROTECTED_SUFFIX)


def _resolve_via_doh(host: str) -> Optional[list[str]]:
    """用 Cloudflare DoH JSON API 查 A record。失敗回 None。"""
    try:
        req = urllib.request.Request(
            f"https://1.1.1.1/dns-query?name={host}&type=A",
            headers={"Accept": "application/dns-json"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        ips = [a["data"] for a in data.get("Answer", []) if a.get("type") == 1]
        return ips or None
    except Exception:
        return None


def _patched_getaddrinfo(host, port, *args, **kwargs):
    if isinstance(host, str) and _is_protected(host):
        if host not in _OVERRIDE:
            ips = _resolve_via_doh(host)
            _OVERRIDE[host] = ips if ips else list(_FALLBACK_IPS)
        ip = _OVERRIDE[host][0]
        return _original_getaddrinfo(ip, port, *args, **kwargs)
    return _original_getaddrinfo(host, port, *args, **kwargs)


def install(refresh: bool = False, verbose: bool = False) -> None:
    """啟用 DNS 繞過。重複呼叫安全。

    refresh=True 時預先用 DoH 解析常用域名；否則 lazy 解析（首次連線時才查）。
    """
    global _installed
    if refresh:
        for host in (
            "gamma-api.polymarket.com",
            "clob.polymarket.com",
            "data-api.polymarket.com",
            "lb-api.polymarket.com",
        ):
            ips = _resolve_via_doh(host)
            if ips:
                _OVERRIDE[host] = ips
                if verbose:
                    print(f"[dns_patch] {host} → {ips}")
            elif verbose:
                print(f"[dns_patch] {host} → fallback {_FALLBACK_IPS}")
    if not _installed:
        socket.getaddrinfo = _patched_getaddrinfo
        _installed = True
