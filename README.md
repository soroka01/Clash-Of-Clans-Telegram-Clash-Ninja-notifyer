# ⚔️ Clash Ninja Telegram Notifier

> Windows Telegram-бот на aiogram, который читает авторизованный Clash Ninja Upgrade Tracker, обновляет dashboards и уведомляет о завершении улучшений.

🌐 **Язык:** [Русский](README.md) · [English](README_EN.md)

![Python](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D4?logo=windows&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-aiogram%203-2CA5E0?logo=telegram&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

## ✨ Обзор

Бот получает статическую страницу и live-feed [Clash Ninja Upgrade Tracker](https://www.clash.ninja/upgrade-tracker), объединяет их в локальный snapshot и показывает текущие улучшения в Telegram. Открытый dashboard обновляется редактированием одного сообщения, а завершения построек, исследований, улучшений питомцев и освобождение назначенных помощников приходят отдельными уведомлениями.

> [!IMPORTANT]
> Для работы нужен полный HTTP-заголовок `Cookie` авторизованной сессии Clash Ninja. Это секрет наравне с Telegram bot token: не отправляйте его другим людям и не коммитьте `config.json`.

> [!NOTE]
> Это неофициальный проект, не связанный с Clash Ninja, Supercell или разработчиками Clash of Clans. Используйте его только со своим аккаунтом и соблюдайте правила соответствующих сервисов.

## 🚀 Основные возможности

| Возможность | Как работает |
| --- | --- |
| Несколько деревень | Общий dashboard и отдельный экран каждого аккаунта |
| Живые таймеры | Открытое сообщение перерисовывается с актуальным обратным отсчётом |
| Точные события | Snapshot сравнивается с предыдущим состоянием в SQLite |
| Помощники | Lab Assistant, Builder's Apprentice и Alchemist показываются у назначенной цели или в блоке свободных |
| Время для каждого чата | Смещение `UTC−12…UTC+14` хранится отдельно в SQLite |
| Восстановление меню | После рестарта бот редактирует сохранённое сообщение или отправляет замену |

Дополнительно бот:

- отслеживает builder, Laboratory и Pet House upgrades;
- не считает простое окончание cooldown помощника его освобождением;
- ограничивает Telegram-меню списком разрешённых user ID;
- отправляет уведомления во все чаты из `notification_chat_ids`;
- ведёт подробный и error-only rotating logs.

## 🏗️ Архитектура

```text
main.py                    # запуск бота, monitor и refresh-задач
app/
├── clash_ninja/
│   ├── client.py          # HTML и /feed/villages.json в одной сессии
│   └── parser.py          # деревни, улучшения и помощники
├── config.py              # чтение и проверка config.json
├── models.py              # Upgrade, HelperStatus и Snapshot
├── monitor.py             # polling, сравнение snapshots и события
├── presentation.py        # Telegram HTML и inline-клавиатуры
├── storage.py             # SQLite state, dashboards и timezone
└── telegram_ui.py         # команды, callbacks и уведомления
```

Поток данных:

```text
Clash Ninja HTML + live feed
          ↓
       parser
          ↓
 snapshot ↔ SQLite
          ↓
 monitor → notifications
          └→ editable dashboards
```

## 🧭 Команды

| Команда | Действие |
| --- | --- |
| `/start` | Открыть главное меню |
| `/menu` | Открыть главное меню |
| `/status` | Сразу открыть dashboard всех аккаунтов |

В меню доступны текущие улучшения, выбор аккаунта, настройка UTC, Clash Ninja, Clash of Clans и GitHub.

## 📋 Требования

- Windows;
- Python **3.14**;
- аккаунт Clash Ninja с заполненным Upgrade Tracker;
- Telegram-бот от [@BotFather](https://t.me/BotFather).

Поддерживаемый launcher — [start.bat](start.bat). Если Windows Python Launcher доступен, он вызывает точный selector `py -3.14`; установленная только более новая версия Python не гарантирует успешное создание `.venv`. Другие ОС текущей версией не поддерживаются.

## ⚙️ Быстрый запуск

1. Склонируйте репозиторий или скачайте [ZIP-архив](https://github.com/soroka01/Clash-Of-Clans-Telegram-Clash-Ninja-notifyer/archive/refs/heads/main.zip).
2. Скопируйте [config.example.json](config.example.json) в `config.json`.
3. Укажите Telegram token, разрешённые user ID, чаты для уведомлений и Clash Ninja cookie.
4. Запустите:

   ```powershell
   .\start.bat
   ```

5. Отправьте боту `/start`.

Launcher создаёт локальную `.venv`, обновляет в ней `pip`, `setuptools` и `wheel`, устанавливает `requirements.txt`, а затем запускает `main.py`. Глобальные Python-пакеты не используются.

Ручной запуск после подготовки окружения:

```powershell
.\.venv\Scripts\python.exe main.py
```

## 🔧 Конфигурация

```json
{
  "bot_token": "PUT_TELEGRAM_BOT_TOKEN_HERE",
  "authorized_user_ids": [123456789],
  "notification_chat_ids": [123456789],
  "poll_interval_seconds": 60,
  "dashboard_refresh_seconds": 10,
  "utc_offset_hours": 5,
  "database_path": "data/clash_ninja_bot.sqlite3",
  "clash_ninja": {
    "tracker_url": "https://www.clash.ninja/upgrade-tracker",
    "cookie_header": "PUT_FULL_COOKIE_HEADER_FROM_LOGGED_IN_CLASH_NINJA_HERE",
    "request_timeout_seconds": 30
  }
}
```

| Поле | Назначение |
| --- | --- |
| `bot_token` | Token Telegram-бота |
| `authorized_user_ids` | User ID, которым разрешены команды и кнопки |
| `notification_chat_ids` | Личные чаты или группы, получающие уведомления |
| `poll_interval_seconds` | Период сетевого обновления; минимум 30 секунд |
| `dashboard_refresh_seconds` | Период перерисовки countdown; минимум 10 секунд |
| `utc_offset_hours` | UTC по умолчанию, целое число от `-12` до `14` |
| `database_path` | Путь к локальной SQLite-базе |
| `clash_ninja.tracker_url` | URL Upgrade Tracker |
| `clash_ninja.cookie_header` | Полное значение HTTP-заголовка `Cookie` |
| `clash_ninja.request_timeout_seconds` | Timeout запроса; минимум 5 секунд |

> [!WARNING]
> Пустой `authorized_user_ids` означает доступ для любого Telegram-пользователя, который найдёт бота. Для приватной установки всегда указывайте хотя бы свой числовой user ID.

## 🍪 Как получить Clash Ninja Cookie

1. Войдите в Clash Ninja и откройте [Upgrade Tracker](https://www.clash.ninja/upgrade-tracker).
2. Нажмите `F12`, откройте **Network** и обновите страницу.
3. Выберите успешный запрос `upgrade-tracker`.
4. Откройте **Headers** → **Request Headers**.
5. Скопируйте всё значение после `Cookie:` в одну строку.
6. Вставьте его в `clash_ninja.cookie_header`.

Cookie имеет срок действия. Если лог сообщает, что Clash Ninja отклонил сессию, войдите на сайт заново и замените значение.

## 🔐 Локальные данные и безопасность

| Путь | Содержимое |
| --- | --- |
| `config.json` | Telegram token и Clash Ninja cookie; исключён из Git |
| `data/clash_ninja_bot.sqlite3` | Последний snapshot, сообщения dashboards и timezone |
| `logs/bot.log` | Подробный rotating log |
| `logs/error.log` | Только ошибки |

Не публикуйте эти файлы. Сохраняйте `config.json` и `data/`, если хотите перенести установку без потери настроек и сохранённых экранов.

## 🔄 Автообновление

`start.bat` проверяет обновления перед запуском:

- в Git-клоне обновление выполняется через `git fetch` и `git pull --ff-only`;
- наличие любых записей в `git status --porcelain`, включая untracked-файлы, пропускает update;
- без Git или в распакованном ZIP launcher скачивает свежий архив через PowerShell;
- при ошибке сети запускается уже установленная версия.

В обоих режимах сохраняются `config.json`, `.venv`, `data/` и `logs/`. ZIP-режим может заменить остальные файлы проекта, поэтому не храните в его каталоге несохранённые изменения исходников.

## 🧪 Ограничения и тестирование

- Парсер зависит от текущей HTML/feed-структуры Clash Ninja и может потребовать обновления после изменений сайта.
- Репозиторий содержит один parser test, но его локальная HTML-fixture `html/Villages - Clash Ninja.html` не публикуется и `pytest` не входит в runtime dependencies. Поэтому test suite сейчас **не воспроизводится из чистого клона**.
- GitHub Actions или другой CI не настроен.
- Синтаксис модулей можно проверить без сетевых credentials:

  ```powershell
  python -m compileall -q main.py app
  ```

## 🩹 Решение проблем

| Симптом | Что проверить |
| --- | --- |
| Clash Ninja отклонил сессию | Получите новый `cookie_header` |
| Бот игнорирует команды | `bot_token` и свой ID в `authorized_user_ids` |
| Нет уведомлений | `notification_chat_ids`, права бота и `logs/error.log` |
| Dashboard показывает старые данные | Доступность Clash Ninja и `poll_interval_seconds` |
| Update пропущен | `git status --short`, включая untracked-файлы |
| Не создаётся `.venv` | Наличие именно Python 3.14 для `py -3.14` |

## 📄 Лицензия

Проект распространяется по [лицензии MIT](LICENSE).

---

⚔️ Актуальные таймеры в одном сообщении, завершения — отдельными уведомлениями.
