#!/usr/bin/env python3
"""Перевод данных Сходни из старого формата (window.START_PAGE = {...}) в JSON.

Запуск из корня проекта:
    python3 tools/migrate-to-json.py

Что делает:
  * data/*.js (кроме манифеста) -> data/*.json;
  * data/manifest.js -> data/manifest.json;
  * themes/manifest.js -> themes/manifest.json;
  * исходные .js переименовывает в .js.bak (не удаляет).
Повторный запуск безопасен: уже сконвертированные файлы пропускаются.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_js_object(path: Path, name: str):
    text = path.read_text(encoding="utf-8")
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


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def backup(path: Path) -> None:
    if path.exists():
        path.rename(path.with_name(path.name + ".bak"))


def main() -> int:
    changed = 0
    data = ROOT / "data"
    themes = ROOT / "themes"

    for path in sorted(data.glob("*.js")):
        if path.name == "manifest.js" or path.name.endswith(".bak"):
            continue
        target = path.with_suffix(".json")
        obj = read_js_object(path, "START_PAGE")
        if obj is None:
            print(f"  пропуск (не START_PAGE): {path}")
            continue
        write_json(target, obj)
        backup(path)
        print(f"  {path.name} -> {target.name}")
        changed += 1

    for path, name, target in (
        (data / "manifest.js", "START_MANIFEST", data / "manifest.json"),
        (themes / "manifest.js", "START_THEMES", themes / "manifest.json"),
    ):
        if path.exists():
            obj = read_js_object(path, name)
            if obj is None:
                print(f"  пропуск (не {name}): {path}")
                continue
            if name == "START_MANIFEST" and isinstance(obj, dict):
                for ws in obj.get("workspaces", []):
                    f = str(ws.get("file", ""))
                    if f.endswith(".js") and (ROOT / f).with_suffix(".json").exists():
                        ws["file"] = f[:-3] + ".json"
            write_json(target, obj)
            backup(path)
            print(f"  {path.relative_to(ROOT)} -> {target.relative_to(ROOT)}")
            changed += 1

    print(f"Готово, файлов сконвертировано: {changed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
