# Clash Ninja Telegram Notifier

[Русская версия](README.md)

An aiogram Telegram bot that reads an authenticated Clash Ninja Upgrade Tracker
page, shows active upgrades, and sends completion notifications.

## Features

- Completion notifications for buildings, Laboratory research, and Pet House upgrades.
- Separate alerts when Lab Assistant, Builder's Apprentice, or Alchemist are
  released by completing an actual upgrade. Their cooldown expiration is ignored.
- `/start` main menu with an all-accounts view, per-account views, and time settings.
- The dashboard message is edited every 10 seconds, keeping countdowns current
  without sending extra messages.
- SQLite snapshots persist across restarts.

## Setup

1. Copy [config.example.json](config.example.json) to `config.json`.
2. Fill in the Telegram token, allowed Telegram IDs, notification chat IDs, and
   an authenticated Clash Ninja `Cookie` request-header value.
   Set `utc_offset_hours` to the desired offset from UTC (for example, `5` for
   `UTC+5`); dashboard and notification times use this timezone.
3. Run [start.bat](start.bat). It creates `.venv`, updates packaging tools in
   that virtual environment, installs dependencies, and starts the bot.
   Before launching, it safely checks GitHub and applies fast-forward updates.
   `config.json`, the SQLite database in `data/`, and logs are ignored by Git
   and are never overwritten. If tracked project files have local edits, the
   update is skipped to preserve them.

`cookie_header` is a session secret. In Chrome/Edge-based browsers, log in to
Clash Ninja, open Upgrade Tracker, press `F12` → **Network**, reload the page,
open the `upgrade-tracker` request, and copy the value after `Cookie:` from
**Request Headers**. Do not commit `config.json` or share that value.

## License

Licensed under the [MIT License](LICENSE).
