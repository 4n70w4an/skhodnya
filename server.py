#!/usr/bin/env python3
"""Сходня — локальный сервер.

Режимы:
  python3 server.py                 # http://127.0.0.1:8080
  python3 server.py --port 9000
  python3 server.py --host 0.0.0.0  # доступ из локальной сети (по умолчанию только localhost)

Возможности:
  * отдаёт статику (index.html, data/, themes/, modules/);
  * блокировка файла на запись: первый открывший — владелец, остальные читают;
  * сохранение рабочего файла (data/*.js) с резервной копией .bak;
  * создание копии воркспейса и запись её в манифест;
  * автоподключение модулей из modules/<id>/module.json.

Запросы не логируются: ни URL, ни результаты проверок.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
LOCK_TTL = 25.0
locks: dict[str, dict] = {}
lock_guard = threading.Lock()
module_routes: dict[tuple[str, str, str], object] = {}
modules_meta: list[dict] = []


# ───────────────────────── helpers ─────────────────────────
def rel_data(path: str) -> str | None:
    """Проверяет, что путь — файл внутри data/ с расширением .js."""
    if not path or path.startswith("/") or ".." in path:
        return None
    if not path.startswith("data/") or not path.endswith(".js"):
        return None
    return path


def read_js_object(path: Path, name: str):
    """Читает window.<name> = {...}; как JSON. None, если формат не наш."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"^\s*window\." + re.escape(name) + r"\s*=\s*", text, re.MULTILINE)
    if not m:
        return None
    body = text[m.end():].strip()
    if body.endswith(";"):
        body = body[:-1].strip()
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def read_manifest():
    return read_js_object(ROOT / "data" / "manifest.js", "START_MANIFEST")


def write_manifest(obj: dict) -> None:
    (ROOT / "data" / "manifest.js").write_text(
        "/* Сходня — манифест воркспейсов. */\n"
        "window.START_MANIFEST = " + json.dumps(obj, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )


def atomic_write(path: Path, content: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    if path.exists():
        try:
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        except OSError:
            pass
    os.replace(tmp, path)


# ───────────────────────── модули ─────────────────────────
class ModuleApi:
    def __init__(self, module_id: str):
        self.id = module_id

    def get(self, path: str, fn) -> None:
        module_routes[(self.id, "GET", path)] = fn

    def post(self, path: str, fn) -> None:
        module_routes[(self.id, "POST", path)] = fn


def load_modules() -> None:
    if not (ROOT / "modules").is_dir():
        return
    for mdir in sorted((ROOT / "modules").glob("*/module.json")):
        try:
            spec = json.loads(mdir.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        mid = spec.get("id") or mdir.parent.name
        enabled = spec.get("enabled", True)
        modules_meta.append({
            "id": mid,
            "title": spec.get("title", mid),
            "assets": spec.get("assets", []),
            "enabled": enabled,
        })
        if not enabled:
            continue
        entry = spec.get("entry")
        if not entry:
            continue
        path = mdir.parent / entry
        if not path.exists():
            continue
        try:
            mspec = importlib.util.spec_from_file_location("svod_mod_" + mid, path)
            module = importlib.util.module_from_spec(mspec)
            assert mspec.loader
            mspec.loader.exec_module(module)
            register = getattr(module, "register", None)
            if callable(register):
                register(ModuleApi(mid))
        except Exception as exc:  # noqa: BLE001
            print(f"[Сходня] модуль {mid} не загрузился: {exc}")


# ───────────────────────── HTTP ─────────────────────────
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    # тишина в консоли: без логов запросов
    def log_message(self, fmt, *args):  # noqa: A003
        return

    # ---------- ответы ----------
    def json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.cors()
        self.end_headers()
        self.wfile.write(body)

    def cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > 4 * 1024 * 1024:
                return {}
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            return {}

    # ---------- методы ----------
    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/config":
            return self.json({"mode": "http", "canWrite": True, "canCreate": True, "modules": modules_meta})
        if path == "/api/modules":
            return self.json(modules_meta)
        if path.startswith("/api/modules/"):
            return self.module_call("GET", path)
        return super().do_GET()

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        payload = self.body()
        if path == "/api/lock":
            return self.api_lock(payload)
        if path == "/api/heartbeat":
            return self.api_heartbeat(payload)
        if path == "/api/unlock":
            return self.api_unlock(payload)
        if path == "/api/save":
            return self.api_save(payload)
        if path == "/api/copy":
            return self.api_copy(payload)
        if path.startswith("/api/modules/"):
            return self.module_call("POST", path, payload)
        self.json({"error": "not found"}, 404)

    # ---------- блокировки ----------
    def api_lock(self, p: dict):
        file = rel_data(str(p.get("file", "")))
        client = str(p.get("client", ""))[:64]
        force = bool(p.get("force"))
        if not file or not client:
            return self.json({"error": "bad request"}, 400)
        now = time.time()
        with lock_guard:
            ent = locks.get(file)
            if ent and now - ent["ts"] >= LOCK_TTL:
                ent = None
            if ent and ent["client"] != client:
                if force and now - ent["ts"] >= LOCK_TTL:
                    pass
                elif force:
                    return self.json({"error": "owner alive"}, 409)
                else:
                    return self.json({"since": ent["ts"], "stale": False}, 409)
            token = secrets.token_hex(8)
            locks[file] = {"client": client, "token": token, "ts": now}
        return self.json({"token": token})

    def api_heartbeat(self, p: dict):
        file = rel_data(str(p.get("file", "")))
        client = str(p.get("client", ""))[:64]
        token = str(p.get("token", ""))
        with lock_guard:
            ent = locks.get(file or "")
            if not ent or ent["client"] != client or ent["token"] != token:
                return self.json({"error": "not owner"}, 409)
            ent["ts"] = time.time()
        return self.json({"ok": True})

    def api_unlock(self, p: dict):
        file = rel_data(str(p.get("file", "")))
        client = str(p.get("client", ""))[:64]
        token = str(p.get("token", ""))
        with lock_guard:
            ent = locks.get(file or "")
            if ent and ent["client"] == client and ent["token"] == token:
                locks.pop(file, None)
        return self.json({"ok": True})

    # ---------- сохранение ----------
    def api_save(self, p: dict):
        file = rel_data(str(p.get("file", "")))
        client = str(p.get("client", ""))[:64]
        token = str(p.get("token", ""))
        content = p.get("content")
        if not file or not isinstance(content, str) or len(content.encode("utf-8")) > 2 * 1024 * 1024:
            return self.json({"error": "bad request"}, 400)
        now = time.time()
        with lock_guard:
            ent = locks.get(file)
            if not ent or ent["client"] != client or ent["token"] != token or now - ent["ts"] >= LOCK_TTL:
                return self.json({"error": "not owner"}, 403)
            ent["ts"] = now
        atomic_write(ROOT / file, content)
        return self.json({"ok": True})

    # ---------- копия воркспейса ----------
    def api_copy(self, p: dict):
        file = rel_data(str(p.get("file", "")))
        client = str(p.get("client", ""))[:64]
        if not file:
            return self.json({"error": "bad request"}, 400)
        src = ROOT / file
        if not src.exists():
            return self.json({"error": "source not found"}, 404)
        stem = src.stem
        n = 2
        while True:
            target_rel = f"data/{stem} ({n}).js"
            if not (ROOT / target_rel).exists():
                break
            n += 1
        target = ROOT / target_rel
        shutil.copy2(src, target)

        page = read_js_object(target, "START_PAGE") or {}
        title = str(page.get("title") or stem) + " (копия)"
        ws_id = stem + "-copy-" + secrets.token_hex(3)
        manifest = read_manifest()
        updated = False
        if manifest and isinstance(manifest.get("workspaces"), list):
            manifest["workspaces"].append({"id": ws_id, "title": title, "file": target_rel})
            write_manifest(manifest)
            updated = True

        now = time.time()
        with lock_guard:
            locks[target_rel] = {"client": client, "token": secrets.token_hex(8), "ts": now}
        return self.json({"file": target_rel, "ws": ws_id if updated else None, "manifestUpdated": updated})

    # ---------- модули ----------
    def module_call(self, method: str, path: str, payload: dict | None = None):
        rest = path[len("/api/modules/"):]
        if "/" not in rest:
            return self.json({"error": "not found"}, 404)
        mid, sub = rest.split("/", 1)
        sub = "/" + sub
        fn = module_routes.get((mid, method, sub))
        if not fn:
            return self.json({"error": "no route"}, 404)
        try:
            result = fn(payload or {})
        except Exception as exc:  # noqa: BLE001
            return self.json({"error": str(exc)}, 500)
        if isinstance(result, tuple):
            status, obj = result
            return self.json(obj, status)
        return self.json(result)


def main() -> None:
    ap = argparse.ArgumentParser(description="Сходня — локальный сервер")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()

    load_modules()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Сходня: http://{args.host}:{args.port}")
    if args.host == "127.0.0.1":
        print("Доступ только с этой машины. Для сети: --host 0.0.0.0")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nСтоп.")


if __name__ == "__main__":
    main()
