# ⚔️ Clash Ninja Telegram Notifier

> A Windows aiogram Telegram bot that reads an authenticated Clash Ninja Upgrade Tracker, refreshes dashboards, and alerts you when upgrades finish.

🌐 **Language:** [Русский](README.md) · [English](README_EN.md)

![Python](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D4?logo=windows&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-aiogram%203-2CA5E0?logo=telegram&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

## ✨ Overview

The bot combines the static [Clash Ninja Upgrade Tracker](https://www.clash.ninja/upgrade-tracker) page with its live feed, stores a local snapshot, and presents current upgrades in Telegram. An open dashboard is refreshed by editing one message, while completed building, research, and pet upgrades and released assigned helpers produce separate alerts.

> [!IMPORTANT]
> The bot needs the complete HTTP `Cookie` header from an authenticated Clash Ninja session. Treat it like the Telegram bot token: never share it and never commit `config.json`.

> [!NOTE]
> This is an unofficial project and is not affiliated with Clash Ninja, Supercell, or the Clash of Clans developers. Use it only with your own account and follow the relevant services' rules.

## 🚀 Highlights

| Capability | How it works |
| --- | --- |
| Multiple villages | One all-account dashboard plus an individual view for each account |
| Live countdowns | The open message is redrawn with a current countdown |
| Durable events | Each snapshot is compared with the previous SQLite state |
| Helpers | Lab Assistant, Builder's Apprentice, and Alchemist appear beside their target or as available |
| Per-chat time | Each chat stores its own `UTC−12…UTC+14` offset |
| Menu recovery | A saved menu is edited after restart or replaced if it is unavailable |

The bot also:

- tracks builder, Laboratory, and Pet House upgrades;
- does not treat cooldown completion alone as a helper release;
- restricts the Telegram menu to configured user IDs;
- sends alerts to every chat in `notification_chat_ids`;
- writes detailed and error-only rotating logs.

## 🏗️ Architecture

```text
main.py                    # bot, monitor, and refresh task bootstrap
app/
├── clash_ninja/
│   ├── client.py          # HTML and /feed/villages.json in one session
│   └── parser.py          # villages, upgrades, and helpers
├── config.py              # config.json loading and validation
├── models.py              # Upgrade, HelperStatus, and Snapshot
├── monitor.py             # polling, snapshot diff, and events
├── presentation.py        # Telegram HTML and inline keyboards
├── storage.py             # SQLite state, dashboards, and timezones
└── telegram_ui.py         # commands, callbacks, and notifications
```

Data flow:

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

## 🧭 Commands

| Command | Action |
| --- | --- |
| `/start` | Open the main menu |
| `/menu` | Open the main menu |
| `/status` | Open the all-account dashboard directly |

The menu provides current upgrades, account selection, UTC settings, Clash Ninja, Clash of Clans, and GitHub links.

## 📋 Requirements

- Windows;
- Python **3.14**;
- a Clash Ninja account with Upgrade Tracker configured;
- a Telegram bot created through [@BotFather](https://t.me/BotFather).

The supported launcher is [start.bat](start.bat). When the Windows Python Launcher is present, it invokes the exact `py -3.14` selector; having only a newer Python version installed does not guarantee that `.venv` can be created. Other operating systems are not supported by the current release.

## ⚙️ Quick start

1. Clone the repository or download the [ZIP archive](https://github.com/soroka01/Clash-Of-Clans-Telegram-Clash-Ninja-notifyer/archive/refs/heads/main.zip).
2. Copy [config.example.json](config.example.json) to `config.json`.
3. Set the Telegram token, allowed user IDs, notification chats, and Clash Ninja cookie.
4. Run:

   ```powershell
   .\start.bat
   ```

5. Send `/start` to the bot.

The launcher creates a local `.venv`, upgrades `pip`, `setuptools`, and `wheel` inside it, installs `requirements.txt`, and starts `main.py`. It does not use global Python packages.

Manual launch after the environment has been prepared:

```powershell
.\.venv\Scripts\python.exe main.py
```

## 🔧 Configuration

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

| Field | Purpose |
| --- | --- |
| `bot_token` | Telegram bot token |
| `authorized_user_ids` | User IDs allowed to use commands and buttons |
| `notification_chat_ids` | Private chats or groups that receive alerts |
| `poll_interval_seconds` | Network refresh period; minimum 30 seconds |
| `dashboard_refresh_seconds` | Countdown redraw period; minimum 10 seconds |
| `utc_offset_hours` | Default UTC offset, an integer from `-12` through `14` |
| `database_path` | Local SQLite database path |
| `clash_ninja.tracker_url` | Upgrade Tracker URL |
| `clash_ninja.cookie_header` | Complete HTTP `Cookie` header value |
| `clash_ninja.request_timeout_seconds` | Request timeout; minimum 5 seconds |

> [!WARNING]
> An empty `authorized_user_ids` list allows any Telegram user who finds the bot to use its menu. Always configure at least your own numeric user ID for a private installation.

## 🍪 Getting the Clash Ninja cookie

1. Sign in to Clash Ninja and open [Upgrade Tracker](https://www.clash.ninja/upgrade-tracker).
2. Press `F12`, open **Network**, and reload the page.
3. Select the successful `upgrade-tracker` request.
4. Open **Headers** → **Request Headers**.
5. Copy the complete value after `Cookie:` as one line.
6. Paste it into `clash_ninja.cookie_header`.

Cookies expire. If the log says Clash Ninja rejected the session, sign in again and replace the value.

## 🔐 Local data and security

| Path | Contents |
| --- | --- |
| `config.json` | Telegram token and Clash Ninja cookie; excluded from Git |
| `data/clash_ninja_bot.sqlite3` | Last snapshot, dashboard messages, and timezones |
| `logs/bot.log` | Detailed rotating log |
| `logs/error.log` | Errors only |

Do not publish these files. Keep `config.json` and `data/` when moving an installation if you want to preserve settings and saved screens.

## 🔄 Automatic updates

`start.bat` checks for updates before launch:

- a Git clone uses `git fetch` followed by `git pull --ff-only`;
- any output from `git status --porcelain`, including untracked files, skips the update;
- without Git, or from an extracted ZIP, the launcher downloads a fresh archive through PowerShell;
- when the network update fails, the installed version still starts.

Both paths preserve `config.json`, `.venv`, `data/`, and `logs/`. ZIP mode may replace every other project file, so do not keep uncommitted source edits in that directory.

## 🧪 Limitations and testing

- The parser depends on Clash Ninja's current HTML and feed structure and may need updates when the site changes.
- The repository contains one parser test, but its local fixture `html/Villages - Clash Ninja.html` is not published and `pytest` is not a runtime dependency. The test suite is therefore **not reproducible from a clean clone**.
- No GitHub Actions or other CI workflow is configured.
- Module syntax can be checked without network credentials:

  ```powershell
  python -m compileall -q main.py app
  ```

## 🩹 Troubleshooting

| Symptom | Check |
| --- | --- |
| Clash Ninja rejects the session | Obtain a new `cookie_header` |
| The bot ignores commands | `bot_token` and your ID in `authorized_user_ids` |
| No alerts arrive | `notification_chat_ids`, bot permissions, and `logs/error.log` |
| The dashboard is stale | Clash Ninja availability and `poll_interval_seconds` |
| The update is skipped | `git status --short`, including untracked files |
| `.venv` is not created | Python 3.14 is available for `py -3.14` |

## 📄 License

Distributed under the [MIT License](LICENSE).

---

⚔️ Current timers stay in one message; completions arrive as separate alerts.
