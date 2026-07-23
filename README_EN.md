# Clash Ninja Telegram Notifier

[Русская версия](README.md) · [GitHub](https://github.com/soroka01/Clash-Of-Clans-Telegram-Clash-Ninja-notifyer)

An aiogram Telegram bot that tracks Clash of Clans upgrades through [Clash Ninja Upgrade Tracker](https://www.clash.ninja/upgrade-tracker). It shows live countdowns, edits one dashboard message instead of spamming the chat, and sends completion alerts.

> [!IMPORTANT]
> The bot needs a `Cookie` from an authenticated Clash Ninja session. Treat it as a secret: never share it or commit `config.json`.

## Highlights

- Completion notifications for buildings, Laboratory research, and Pet House upgrades.
- Helper icons beside their actual target upgrade: 🧑‍🔬 Lab Assistant, 👷 Builder's Apprentice, and ⚗️ Alchemist.
- A separate block for genuinely available helpers. Cooldown completion alone does not trigger a release alert.
- All-accounts dashboard and individual-account dashboards.
- The open dashboard is edited every 10 seconds, keeping countdowns current without sending new messages.
- Per-chat timezone selection from `UTC−12` through `UTC+14` in the bot menu.
- SQLite state persistence across restarts.

## Requirements

- Windows;
- Python 3.14 or newer;
- a Clash Ninja account with Upgrade Tracker configured;
- a Telegram bot created with [@BotFather](https://t.me/BotFather).

Git is optional: `start.bat` can update the project without it.

## Quick start

1. Clone this repository or download the [ZIP archive](https://github.com/soroka01/Clash-Of-Clans-Telegram-Clash-Ninja-notifyer/archive/refs/heads/main.zip).
2. Copy [config.example.json](config.example.json) to `config.json`.
3. Fill in the Telegram token, your Telegram ID, and the Clash Ninja cookie.
4. Double-click [start.bat](start.bat), or run it in PowerShell:

   ```powershell
   .\start.bat
   ```

5. Open the bot in Telegram and send `/start`.

On its first run, the script creates `.venv`, updates `pip`, `setuptools`, and `wheel` inside that virtual environment only, installs dependencies, and starts the bot. No global Python packages are used.

## `config.json`

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
| `bot_token` | Token provided by BotFather. |
| `authorized_user_ids` | Telegram user IDs allowed to use the menu. |
| `notification_chat_ids` | Private chats or groups that receive alerts. Add the bot to the group first. |
| `poll_interval_seconds` | Clash Ninja polling period; 60 seconds by default. |
| `dashboard_refresh_seconds` | Open-dashboard refresh period; 10 seconds by default. |
| `utc_offset_hours` | Default timezone offset, e.g. `5` for `UTC+5`. This can be changed per chat from the bot menu. |
| `database_path` | Local SQLite database path. Keep this file to preserve bot state and chat settings. |
| `clash_ninja.cookie_header` | Full `Cookie` HTTP-header value from an authenticated Clash Ninja session. |

## Getting the Clash Ninja cookie

You need the complete HTTP `Cookie` header value, not a browser cookie database file.

1. Log in to Clash Ninja and open [Upgrade Tracker](https://www.clash.ninja/upgrade-tracker).
2. Press `F12` and open **Network**.
3. Reload the page with `Ctrl+R`.
4. Select the `upgrade-tracker` request with status `200`.
5. Open **Headers** → **Request Headers**.
6. Copy everything after `Cookie:` on one line.
7. Paste it into `clash_ninja.cookie_header` in `config.json`.

Cookies expire. If the log says Clash Ninja rejected the session, log in again and repeat these steps.

## Menu and notifications

Send `/start` to open the main menu.

- **Current upgrades** — opens the all-accounts dashboard; use buttons to select one account.
- **Time settings** — changes the timezone for the current Telegram chat.
- **Clash Ninja** — opens Upgrade Tracker in a browser.
- **GitHub** — opens this repository.

An assigned helper appears directly beside the upgrade it is working on, for example `🧑‍🔬 Freeze Spell`. A free helper appears in the **🤖 Available helpers** block and produces a separate notification. A helper merely finishing cooldown is not reported as an upgrade-completion release.

After a restart, the bot restores the last saved menu by its message ID. If the message was deleted or Telegram no longer allows it to be edited, the bot automatically sends a replacement with the same view. If no menu exists yet, a main menu is sent to chats listed in `notification_chat_ids`.

## Automatic updates

`start.bat` checks for updates every time it starts.

- **Git installed and repository cloned:** it uses the safe `git pull --ff-only` flow. If tracked source files have local edits, the update is skipped to protect them.
- **No Git or project downloaded as ZIP:** it downloads the latest project ZIP from GitHub through built-in PowerShell and refreshes the source files.

In both cases, `config.json`, `.venv`, `data/`, and `logs/` are preserved. In ZIP mode, do not edit source files locally: a future update may replace them with the current GitHub version.

## Important local files

| Path | Contents |
| --- | --- |
| `config.json` | Bot token and Clash Ninja cookie; never committed. |
| `data/clash_ninja_bot.sqlite3` | Snapshot state, dashboards, and timezone settings. |
| `logs/bot.log` | Detailed runtime log. |
| `logs/error.log` | Errors only. |

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| `Clash Ninja rejected the session` | Refresh `cookie_header` using the instructions above. |
| The bot ignores `/start` | Check `bot_token` and add your numeric Telegram ID to `authorized_user_ids`. |
| No alerts arrive | Check `notification_chat_ids`, bot permissions in that chat, and `logs/error.log`. |
| Update fails | Check your internet connection. The current installed version will still start if GitHub is unavailable. |
| Times are wrong | Open **Time settings** in the bot and choose the correct UTC offset. |

## License

Distributed under the [MIT License](LICENSE).
