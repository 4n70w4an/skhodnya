/* Сходня — манифест воркспейсов.
   Формат: window.START_MANIFEST = { ... } (валидный JSON внутри).
   Новый воркспейс: создать data/<id>.js по образцу data/home.js и добавить строку в workspaces. */
window.START_MANIFEST = {
  "title": "Сходня",
  "subtitle": "домашняя лаборатория",
  "defaultWorkspace": "home",
  "workspaces": [
    { "id": "home", "title": "Дом", "file": "data/home.js" },
    { "id": "work", "title": "Работа", "file": "data/work.js" }
  ]
};
