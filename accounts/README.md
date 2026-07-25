# JSON-аккаунты

В режиме `"data_source": "json"` положите сюда отдельный JSON-файл для каждого аккаунта.

Поддерживается исходный экспорт из игры (как `json.json`). Для имени аккаунта добавьте в файл поле `name`; если его нет, используется имя файла. Например:

```json
{
  "name": "Kreker",
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

Имена файлов могут быть любыми, например `kreker.json`, `luv_u_my_cutie.json` и `soroka01.json`.
