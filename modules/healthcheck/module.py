"""Сходня — модуль проверок доступности.

Типы: http, https, ping, tcp. Проверки выполняются на сервере (браузер не может
кросс-доменные запросы), только для приватных адресов. Результаты не логируются.
"""
from __future__ import annotations

import ipaddress
import re
import socket
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

TIMEOUT_DEFAULT = 2.0
TIMEOUT_MAX = 5.0


def _target_host(payload: dict) -> str:
    """Хост проверки: явный host или хост из ссылки элемента."""
    host = str(payload.get("host") or "").strip()
    if host:
        return host
    try:
        return urlparse(str(payload.get("url") or "")).hostname or ""
    except ValueError:
        return ""


def _is_private(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return True
    return False


def register(api):
    api.post("/check", check)


def check(payload: dict):
    kind = str(payload.get("type") or "")
    try:
        timeout = float(payload.get("timeout") or TIMEOUT_DEFAULT)
    except (TypeError, ValueError):
        timeout = TIMEOUT_DEFAULT
    timeout = max(0.3, min(timeout, TIMEOUT_MAX))

    if kind in ("http", "https"):
        return _http(payload, timeout)
    if kind == "ping":
        return _ping(payload, timeout)
    if kind == "tcp":
        return _tcp(payload, timeout)
    return 400, {"ok": False, "error": "unknown type"}


def _http(payload: dict, timeout: float):
    url = str(payload.get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return 400, {"ok": False, "error": "bad url"}
    if not _is_private(parsed.hostname):
        return 403, {"ok": False, "error": "только приватные адреса"}

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": "Svod/0.0.1"})
    started = time.perf_counter()
    code = None
    error = None
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            code = resp.status
            resp.read(64)
    except urllib.error.HTTPError as exc:
        code = exc.code
    except Exception as exc:  # noqa: BLE001
        error = type(exc).__name__

    ms = round((time.perf_counter() - started) * 1000)
    ok = code is not None and code < 500
    return 200, {"ok": ok, "ms": ms, "code": code, "error": error}


def _ping(payload: dict, timeout: float):
    host = _target_host(payload)
    if not host:
        return 400, {"ok": False, "error": "no host"}
    if not _is_private(host):
        return 403, {"ok": False, "error": "только приватные адреса"}
    wait = max(1, int(round(timeout)))
    try:
        proc = subprocess.run(
            ["ping", "-c", "1", "-W", str(wait), host],
            capture_output=True, text=True, timeout=timeout + 2,
        )
    except FileNotFoundError:
        return 500, {"ok": False, "error": "ping не установлен"}
    except subprocess.TimeoutExpired:
        return 200, {"ok": False, "error": "timeout"}
    m = re.search(r"time[=<]([\d.]+)\s*ms", proc.stdout)
    ok = proc.returncode == 0 and m is not None
    ms = float(m.group(1)) if m else None
    error = None
    if not ok:
        low = ((proc.stderr or "") + (proc.stdout or "")).lower()
        if "not permitted" in low or "операция не позволена" in low or "cap_net_raw" in low:
            error = "нет прав на ICMP (ping должен иметь cap_net_raw)"
        else:
            error = "нет ответа"
    return 200, {"ok": ok, "ms": round(ms) if ms is not None else None, "error": error}


def _tcp(payload: dict, timeout: float):
    host = _target_host(payload)
    try:
        port = int(payload.get("port") or 0)
    except (TypeError, ValueError):
        port = 0
    if not host or not (0 < port < 65536):
        return 400, {"ok": False, "error": "bad host/port"}
    if not _is_private(host):
        return 403, {"ok": False, "error": "только приватные адреса"}
    started = time.perf_counter()
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        ms = round((time.perf_counter() - started) * 1000)
        return 200, {"ok": True, "ms": ms}
    except OSError:
        ms = round((time.perf_counter() - started) * 1000)
        return 200, {"ok": False, "ms": ms, "error": "нет соединения"}
