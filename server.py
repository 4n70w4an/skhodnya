#!/usr/bin/env python3
"""Сходня — локальный сервер.

  python3 server.py [--host 127.0.0.1] [--port 8080] [--data-dir DIR]
  python3 server.py --browse-root /srv --browse-root /mnt

Данные — JSON-файлы в папке закладок (по умолчанию data/). Папку можно выбрать
в настройках приложения; путь хранится в config.json рядом с server.py.

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
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config.json"
LOCK_TTL = 25.0

locks: dict[str, dict] = {}
lock_guard = threading.Lock()
module_routes: dict[tuple[str, str, str], object] = {}
modules_meta: list[dict] = []

DATA_DIR: Path = ROOT / "data"
BROWSE_ROOTS: list[Path] = [ROOT.resolve(), Path.home().resolve()]


# ───────────────────────── пути и конфиг ─────────────────────────
def _writable(path: Path) -> bool:
    return path.is_dir() and os.access(path, os.W_OK)


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _allowed(path: Path) -> bool:
    return any(_within(path, root) for root in BROWSE_ROOTS)


def load_config() -> None:
    global DATA_DIR
    raw = None
    if CONFIG_FILE.exists():
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("dataDir")
        except (OSError, json.JSONDecodeError):
            raw = None
    if raw:
        path = Path(str(raw)).expanduser()
        if not path.is_absolute():
            path = (ROOT / path).resolve()
        if path.is_dir():
            DATA_DIR = path
            return
    DATA_DIR = ROOT / "data"


def save_config() -> None:
    CONFIG_FILE.write_text(
        json.dumps({"dataDir": str(DATA_DIR)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def data_path(rel: str) -> Path | None:
    """Логический путь data/<...>.json -> физический файл в DATA_DIR."""
    if not rel or not rel.startswith("data/") or not rel.endswith(".json"):
        return None
    if ".." in rel.split("/"):
        return None
    target = (DATA_DIR / rel[len("data/"):]).resolve()
    if not _within(target, DATA_DIR):
        return None
    return target


def rel_for(path: Path) -> str:
    return "data/" + path.relative_to(DATA_DIR).as_posix()


def config_payload() -> dict:
    return {
        "mode": "http",
        "canWrite": True,
        "canCreate": True,
        "modules": modules_meta,
        "dataDir": str(DATA_DIR),
        "dataDirWritable": _writable(DATA_DIR),
    }


# ───────────────────────── данные ─────────────────────────
def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_manifest():
    return read_json(DATA_DIR / "manifest.json")


def write_manifest(obj: dict) -> None:
    (DATA_DIR / "manifest.json").write_text(
        json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
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


_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _slug(value: str) -> str:
    out = []
    for ch in (value or "").lower():
        if ch in _TRANSLIT:
            out.append(_TRANSLIT[ch])
        elif ch.isalnum() or ch in "-_":
            out.append(ch)
        else:
            out.append("-")
    slug = re.sub(r"-+", "-", "".join(out)).strip("-")
    return slug or "workspace"


def _workspace_files():
    if not DATA_DIR.is_dir():
        return []
    out = []
    for path in sorted(DATA_DIR.rglob("*.json")):
        if path.name == "manifest.json" or ".personal." in path.name:
            continue
        out.append((rel_for(path), path))
    return out


def collect_workspaces():
    items = []
    for rel, path in _workspace_files():
        page = read_json(path) or {}
        items.append({
            "file": rel,
            "id": str(page.get("id") or path.stem),
            "title": str(page.get("title") or path.stem),
        })
    return items


def ensure_manifest():
    """Если манифеста нет — собрать его из найденных воркспейсов."""
    existing = read_manifest()
    if isinstance(existing, dict) and isinstance(existing.get("workspaces"), list):
        return existing
    items = collect_workspaces()
    if not items:
        return None
    workspaces = []
    ids = set()
    for item in items:
        base = _slug(item["id"])
        ws_id = base
        n = 2
        while ws_id in ids:
            ws_id = f"{base}-{n}"
            n += 1
        ids.add(ws_id)
        workspaces.append({"id": ws_id, "title": item["title"], "file": item["file"]})
    manifest = {
        "title": "Сходня",
        "subtitle": "",
        "defaultWorkspace": workspaces[0]["id"],
        "workspaces": workspaces,
    }
    try:
        write_manifest(manifest)
    except OSError as exc:
        print(f"[Сходня] не удалось создать манифест: {exc}")
    return manifest


def scan_workspaces():
    manifest = read_manifest() or {}
    workspaces = manifest.get("workspaces") if isinstance(manifest.get("workspaces"), list) else []
    known = {str(w.get("file")) for w in workspaces if isinstance(w, dict)}
    items = []
    for item in collect_workspaces():
        item["inManifest"] = item["file"] in known
        items.append(item)
    return items, manifest


def parse_workspace_text(text: str):
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) and isinstance(obj.get("groups"), list) else None
    except json.JSONDecodeError:
        return None


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

    def log_message(self, fmt, *args):  # noqa: A003
        return

    def cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.cors()
        self.end_headers()
        self.wfile.write(body)

    def body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > 4 * 1024 * 1024:
                return {}
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            return {}

    def translate_path(self, path):  # noqa: A003
        p = urlparse(path).path
        if p.startswith("/data/"):
            rel = unquote(p[len("/data/"):])
            if not rel.endswith(".json") or ".." in rel.split("/"):
                return str(ROOT / "__forbidden__")
            target = (DATA_DIR / rel).resolve()
            if not _within(target, DATA_DIR):
                return str(ROOT / "__forbidden__")
            return str(target)
        return super().translate_path(path)

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path == "/config.json" or path.startswith("/.git/"):
            return self.json({"error": "not found"}, 404)
        if path == "/api/config":
            return self.json(config_payload())
        if path == "/api/scan":
            ensure_manifest()
            items, manifest = scan_workspaces()
            return self.json({"items": items, "manifest": manifest or {}, "dataDir": str(DATA_DIR)})
        if path == "/api/roots":
            roots = [{"name": str(r), "path": str(r)} for r in BROWSE_ROOTS if r.is_dir()]
            return self.json({"roots": roots})
        if path == "/api/browse":
            return self.api_browse()
        if path == "/api/modules":
            return self.json(modules_meta)
        if path.startswith("/api/modules/"):
            return self.module_call("GET", path)
        return super().do_GET()

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        payload = self.body()
        routes = {
            "/api/lock": self.api_lock,
            "/api/heartbeat": self.api_heartbeat,
            "/api/unlock": self.api_unlock,
            "/api/save": self.api_save,
            "/api/copy": self.api_copy,
            "/api/manifest/add": self.api_manifest_add,
            "/api/config": self.api_set_config,
            "/api/workspace/create": self.api_create_workspace,
        }
        if path in routes:
            return routes[path](payload)
        if path.startswith("/api/modules/"):
            return self.module_call("POST", path, payload)
        self.json({"error": "not found"}, 404)

    # ---------- папки ----------
    def api_browse(self):
        q = parse_qs(urlparse(self.path).query)
        raw = (q.get("path") or [""])[0]
        base = Path(raw).expanduser() if raw else DATA_DIR
        if not base.is_absolute():
            base = (ROOT / base).resolve()
        else:
            base = base.resolve()
        if not _allowed(base):
            return self.json({"error": "путь вне разрешённых папок"}, 403)
        if not base.is_dir():
            return self.json({"error": "папка не найдена"}, 404)
        dirs = []
        try:
            for child in sorted(base.iterdir()):
                if child.is_dir() and not child.name.startswith("."):
                    dirs.append({
                        "name": child.name,
                        "path": str(child),
                        "writable": os.access(child, os.W_OK),
                    })
        except OSError as exc:
            return self.json({"error": str(exc)}, 400)
        parent = None
        for root in BROWSE_ROOTS:
            if base != root.resolve() and _within(base, root):
                parent = str(base.parent)
                break
        return self.json({
            "path": str(base),
            "parent": parent,
            "dirs": dirs,
            "writable": os.access(base, os.W_OK),
        })

    def api_set_config(self, p: dict):
        raw = p.get("dataDir")
        if not isinstance(raw, str) or not raw.strip():
            return self.json({"error": "папка не выбрана", "hint": "Укажите папку для закладок"}, 400)
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = (ROOT / path).resolve()
        else:
            path = path.resolve()
        if not _allowed(path):
            return self.json({"error": "путь вне разрешённых папок",
                              "hint": "Запустите сервер с --browse-root <папка>"}, 403)
        if not path.is_dir():
            return self.json({"error": "папка не существует", "hint": "Выберите существующую папку"}, 400)
        if not os.access(path, os.W_OK):
            return self.json({"error": "папка недоступна для записи",
                              "hint": "Выберите другую папку или измените права"}, 400)
        global DATA_DIR
        DATA_DIR = path
        save_config()
        ensure_manifest()
        return self.json(config_payload())

    # ---------- блокировки ----------
    def api_lock(self, p: dict):
        file = p.get("file") if isinstance(p.get("file"), str) else ""
        if data_path(file) is None:
            return self.json({"error": "bad request"}, 400)
        client = str(p.get("client", ""))[:64]
        force = bool(p.get("force"))
        if not client:
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
        file = str(p.get("file", ""))
        client = str(p.get("client", ""))[:64]
        token = str(p.get("token", ""))
        with lock_guard:
            ent = locks.get(file)
            if not ent or ent["client"] != client or ent["token"] != token:
                return self.json({"error": "not owner"}, 409)
            ent["ts"] = time.time()
        return self.json({"ok": True})

    def api_unlock(self, p: dict):
        file = str(p.get("file", ""))
        client = str(p.get("client", ""))[:64]
        token = str(p.get("token", ""))
        with lock_guard:
            ent = locks.get(file)
            if ent and ent["client"] == client and ent["token"] == token:
                locks.pop(file, None)
        return self.json({"ok": True})

    # ---------- сохранение ----------
    def api_save(self, p: dict):
        file = str(p.get("file", ""))
        path = data_path(file)
        content = p.get("content")
        if path is None or not isinstance(content, str) or len(content.encode("utf-8")) > 2 * 1024 * 1024:
            return self.json({"error": "bad request"}, 400)
        try:
            json.loads(content)
        except json.JSONDecodeError:
            return self.json({"error": "invalid json"}, 400)
        now = time.time()
        with lock_guard:
            ent = locks.get(file)
            if not ent or ent["client"] != str(p.get("client", ""))[:64] or ent["token"] != str(p.get("token", "")) or now - ent["ts"] >= LOCK_TTL:
                return self.json({"error": "not owner"}, 403)
            ent["ts"] = now
        atomic_write(path, content)
        return self.json({"ok": True})

    # ---------- копия воркспейса ----------
    def api_copy(self, p: dict):
        src = data_path(str(p.get("file", "")))
        client = str(p.get("client", ""))[:64]
        if src is None or not src.exists():
            return self.json({"error": "source not found"}, 404)
        page = read_json(src) or {}
        stem = src.stem
        n = 2
        target = DATA_DIR / f"{stem} ({n}).json"
        while target.exists():
            n += 1
            target = DATA_DIR / f"{stem} ({n}).json"
        target.write_text(json.dumps(page, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rel = rel_for(target)

        title = str(page.get("title") or stem) + " (копия)"
        manifest = read_manifest() or {}
        if not isinstance(manifest.get("workspaces"), list):
            manifest["workspaces"] = []
        known_ids = {str(w.get("id")) for w in manifest["workspaces"] if isinstance(w, dict)}
        ws_id = _slug(stem) + "-copy-" + secrets.token_hex(3)
        while ws_id in known_ids:
            ws_id = _slug(stem) + "-copy-" + secrets.token_hex(3)
        manifest["workspaces"].append({"id": ws_id, "title": title, "file": rel})
        write_manifest(manifest)
        now = time.time()
        with lock_guard:
            locks[rel] = {"client": client, "token": secrets.token_hex(8), "ts": now}
        return self.json({"file": rel, "ws": ws_id, "manifest": manifest})

    # ---------- манифест ----------
    def api_manifest_add(self, p: dict):
        files = p.get("files") or []
        if not isinstance(files, list) or not files:
            return self.json({"error": "bad request"}, 400)
        manifest = read_manifest() or {}
        if not isinstance(manifest.get("workspaces"), list):
            return self.json({"error": "манифест не читается — проверьте manifest.json"}, 400)
        known = {str(w.get("file")) for w in manifest["workspaces"] if isinstance(w, dict)}
        ids = {str(w.get("id")) for w in manifest["workspaces"] if isinstance(w, dict)}
        added = []
        for raw in files[:50]:
            path = data_path(str(raw))
            if path is None or not path.is_file() or str(raw) in known:
                continue
            page = read_json(path) or {}
            title = str(page.get("title") or path.stem)
            base = _slug(str(page.get("id") or path.stem))
            ws_id = base
            n = 2
            while ws_id in ids:
                ws_id = f"{base}-{n}"
                n += 1
            entry = {"id": ws_id, "title": title, "file": str(raw)}
            manifest["workspaces"].append(entry)
            known.add(str(raw))
            ids.add(ws_id)
            added.append(entry)
        if added:
            write_manifest(manifest)
        return self.json({"ok": True, "added": added, "manifest": manifest})

    # ---------- создание воркспейса ----------
    def api_create_workspace(self, p: dict):
        title = str(p.get("title") or "").strip()
        if not title:
            return self.json({"error": "нужно название", "hint": "Введите название воркспейса"}, 400)
        if not _writable(DATA_DIR):
            return self.json({"error": "папка недоступна для записи",
                              "hint": "Выберите другую папку закладок в настройках"}, 400)
        base = _slug(title)
        n = 2
        target = DATA_DIR / f"{base}.json"
        while target.exists():
            target = DATA_DIR / f"{base}-{n}.json"
            n += 1
        page = {"id": base, "title": title, "subtitle": "", "groups": []}
        try:
            target.write_text(json.dumps(page, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError:
            return self.json({"error": "папка недоступна для записи",
                              "hint": "Выберите другую папку закладок в настройках"}, 400)
        rel = rel_for(target)
        manifest = read_manifest() or {}
        if not isinstance(manifest.get("workspaces"), list):
            manifest["workspaces"] = []
        ids = {str(w.get("id")) for w in manifest["workspaces"] if isinstance(w, dict)}
        ws_id = base
        n = 2
        while ws_id in ids:
            ws_id = f"{base}-{n}"
            n += 1
        entry = {"id": ws_id, "title": title, "file": rel}
        manifest["workspaces"].append(entry)
        write_manifest(manifest)
        return self.json({"ok": True, "entry": entry, "manifest": manifest})

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
    ap.add_argument("--data-dir", help="папка закладок (по умолчанию data/)")
    ap.add_argument("--browse-root", action="append", default=[],
                    help="разрешённая папка для выбора хранилища (можно несколько)")
    args = ap.parse_args()

    global DATA_DIR
    for raw in args.browse_root:
        BROWSE_ROOTS.append(Path(raw).expanduser().resolve())
    load_config()
    if args.data_dir:
        candidate = Path(args.data_dir).expanduser()
        if not candidate.is_absolute():
            candidate = (ROOT / candidate).resolve()
        if candidate.is_dir():
            DATA_DIR = candidate
            save_config()
        else:
            print(f"[Сходня] папка не найдена: {candidate}")

    ensure_manifest()
    load_modules()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Сходня: http://{args.host}:{args.port}")
    print(f"Закладки: {DATA_DIR}")
    if args.host == "127.0.0.1":
        print("Доступ только с этой машины. Для сети: --host 0.0.0.0")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nСтоп.")


if __name__ == "__main__":
    main()
