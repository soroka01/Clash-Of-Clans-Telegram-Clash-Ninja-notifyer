# JSON-аккаунты

В режиме `"data_source": "json"` положите сюда отдельный JSON-файл для каждого аккаунта.

Поддерживается исходный экспорт из игры (как `json.json`). Ничего добавлять в JSON не нужно: именем аккаунта считается имя файла без `.json`. Например, сохраните экспорт как `Greatness.json`:

```json
{
  "tag": "#2URGQ0VQL",
  "timestamp": 1784976658,
  "buildings": [],
  "traps": [],
  "units": [],
  "spells": [],
  "heroes": [],
  "pets": [],
  "helpers": []
}
```

Имена файлов могут быть любыми, например `Greatness.json`, `luv_u_my_cutie.json` и `soroka01.json`.
