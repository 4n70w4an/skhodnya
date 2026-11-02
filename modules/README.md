# Модули Сходни

Модуль — самодостаточная папка: бэкенд на Python (необязательно), стили и логика
на JS. Ядро не знает про модуль ничего, пока сервер не найдёт `module.json`.

## Структура

```
modules/<id>/
  module.json     описание (id, title, version, entry, assets, enabled)
  module.py       необязательный бэкенд: def register(api): ...
  module.css      стили модуля (только со своим префиксом)
  module.js       логика: window.Svod.registerModule({...})
```

`module.json`:

```json
{
  "id": "healthcheck",
  "title": "Проверки доступности",
  "version": "0.1.0",
  "entry": "module.py",
  "assets": ["module.css", "module.js"],
  "enabled": true
}
```

## Бэкенд

```python
def register(api):
    api.post("/check", handler)   # → POST /api/modules/<id>/check
    api.get("/status", handler)   # → GET  /api/modules/<id>/status
```

Обработчик получает dict (тело запроса) и возвращает dict или `(status, dict)`.
Исключение превращается в ответ 500.

## Фронтенд

```js
(function () {
  const S = window.Svod;
  if (!S) return;
  S.registerModule({
    id: "mymodule",
    onBoot() {},                          // при подключении
    onRender({ root, page, edit }) {},     // после каждой перерисовки
    editorSection(item, ctx) {             // секция в редакторе; ctx.getUrl() — текущий URL
      const el = document.createElement("div");
      return { el, get() { return item.checks; }, refresh() {} };
    },
  });
})();
```

Доступно из `window.Svod`: `state`, `api(path, opts)`, `esc`, `hostOf`, `uid`,
`registerModule`, `editorSections`, `afterRender`.

## Правила

- ассеты подключаются автоматически по списку `assets`;
- CSS модуля должен быть со своим префиксом (`.hc-*`), чтобы не течь в ядро;
- в `file://` модулей нет — страница обязана работать без них;
- проверки доступности и прочие сетевые действия — только с сервера.
