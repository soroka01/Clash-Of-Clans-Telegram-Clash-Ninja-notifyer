from __future__ import annotations

import json
import logging
import os
import re
import threading
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.sources.json_accounts.parser import export_tag, export_time, export_village_id

logger = logging.getLogger(__name__)

MAX_NAME_LENGTH = 40
TRASH_DIRECTORY = "_trash"
_FORBIDDEN_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul", *(f"com{number}" for number in range(1, 10)), *(f"lpt{number}" for number in range(1, 10))}
)


class AccountStoreError(Exception):
    """A user-facing problem with an account operation (the message is in Russian)."""


@dataclass(frozen=True, slots=True)
class AccountRecord:
    name: str
    path: Path
    village_id: str
    tag: str | None
    exported_at: datetime | None
    size: int


def sanitize_name(raw: str) -> str | None:
    """Make a safe, readable file stem out of user input, or None if nothing usable is left."""
    name = unicodedata.normalize("NFC", raw or "")
    name = _FORBIDDEN_CHARACTERS.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if name.casefold().endswith(".json"):
        name = name[: -len(".json")].strip(" .")
    name = name[:MAX_NAME_LENGTH].strip(" .")
    if not name or name.split(".")[0].casefold() in _RESERVED_NAMES:
        return None
    return name


class AccountStore:
    """The ``accounts/`` folder: one ``<name>.json`` game export per account.

    The file name is the account name. All methods are synchronous and thread-safe; async callers
    run them through ``asyncio.to_thread``.
    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._lock = threading.RLock()
        self._cache: dict[Path, tuple[int, int, dict[str, Any], AccountRecord]] = {}
        self._reported_errors: dict[Path, int] = {}

    @property
    def directory(self) -> Path:
        return self._directory

    def ensure_directory(self) -> bool:
        """Create the folder if needed. Returns True when it had to be created."""
        if self._directory.exists():
            return False
        self._directory.mkdir(parents=True, exist_ok=True)
        return True

    # ----- reading -----------------------------------------------------------------

    def records(self) -> list[AccountRecord]:
        return [record for record, _ in self.load_all()]

    def load_all(self) -> list[tuple[AccountRecord, dict[str, Any]]]:
        """Every readable account with its payload, sorted by name. Unchanged files are not re-read."""
        with self._lock:
            if not self._directory.exists():
                return []
            loaded: list[tuple[AccountRecord, dict[str, Any]]] = []
            present: set[Path] = set()
            for path in sorted(self._directory.glob("*.json"), key=lambda item: item.name.casefold()):
                present.add(path)
                entry = self._load(path)
                if entry:
                    loaded.append(entry)
            for gone in set(self._cache) - present:
                del self._cache[gone]
            return loaded

    def _load(self, path: Path) -> tuple[AccountRecord, dict[str, Any]] | None:
        try:
            stat = path.stat()
            cached = self._cache.get(path)
            if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
                return cached[3], cached[2]
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(payload, dict):
                raise ValueError("корень JSON должен быть объектом")
        except (OSError, ValueError) as error:  # JSONDecodeError and UnicodeDecodeError are ValueErrors
            self._report_unreadable(path, error)
            # Keep serving the last good copy: a half-saved file must not make the account vanish
            # (and then look "new" when it comes back).
            cached = self._cache.get(path)
            return (cached[3], cached[2]) if cached and path.exists() else None
        record = AccountRecord(
            name=path.stem,
            path=path,
            village_id=export_village_id(payload, path.stem),
            tag=export_tag(payload),
            exported_at=export_time(payload),
            size=stat.st_size,
        )
        self._cache[path] = (stat.st_mtime_ns, stat.st_size, payload, record)
        self._reported_errors.pop(path, None)
        return record, payload

    def _report_unreadable(self, path: Path, error: Exception) -> None:
        try:
            marker = path.stat().st_mtime_ns
        except OSError:
            marker = 0
        if self._reported_errors.get(path) != marker:
            self._reported_errors[path] = marker
            logger.error("Не удалось прочитать JSON аккаунта %s: %s", path.name, error)

    def find_by_name(self, name: str) -> AccountRecord | None:
        wanted = name.casefold()
        return next((record for record in self.records() if record.name.casefold() == wanted), None)

    def find_by_village_id(self, village_id: str) -> AccountRecord | None:
        return next((record for record in self.records() if record.village_id == village_id), None)

    def find_by_tag(self, tag: str | None) -> AccountRecord | None:
        if not tag:
            return None
        return next((record for record in self.records() if record.tag and record.tag.casefold() == tag.casefold()), None)

    def read_text(self, record: AccountRecord) -> bytes:
        return record.path.read_bytes()

    # ----- writing -----------------------------------------------------------------

    def unique_name(self, base: str) -> str:
        """``base`` if free, otherwise ``base 2``, ``base 3`` ... (case-insensitive)."""
        with self._lock:
            taken = {record.name.casefold() for record in self.records()}
            taken |= {path.stem.casefold() for path in self._directory.glob("*.json")} if self._directory.exists() else set()
            candidate, number = base, 2
            while candidate.casefold() in taken:
                suffix = f" {number}"
                candidate = f"{base[: MAX_NAME_LENGTH - len(suffix)]}{suffix}"
                number += 1
            return candidate

    def save(self, name: str, content: str | bytes) -> AccountRecord:
        """Write ``<name>.json`` atomically (replacing an existing file) and return its record."""
        safe = sanitize_name(name)
        if safe is None:
            raise AccountStoreError("Недопустимое имя аккаунта.")
        data = content.encode("utf-8") if isinstance(content, str) else content
        with self._lock:
            self.ensure_directory()
            target = self._path_for(safe)
            temporary = target.with_name(f".{target.stem}.tmp")
            try:
                with open(temporary, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            entry = self._load(target)
            if entry is None:
                raise AccountStoreError("Файл сохранён, но его не удалось прочитать обратно.")
            return entry[0]

    def rename(self, record: AccountRecord, new_name: str) -> AccountRecord:
        safe = sanitize_name(new_name)
        if safe is None:
            raise AccountStoreError("Недопустимое имя аккаунта: уберите спецсимволы и не используйте имена вроде CON.")
        with self._lock:
            clash = self.find_by_name(safe)
            if clash and clash.path != record.path:
                raise AccountStoreError(f"Имя «{safe}» уже занято другим аккаунтом.")
            if not record.path.exists():
                raise AccountStoreError("Аккаунт уже удалён.")
            target = self._directory / f"{safe}.json"  # may differ from the old name only by letter case
            if target.resolve().parent != self._directory.resolve():
                raise AccountStoreError("Недопустимое имя аккаунта.")
            record.path.replace(target)
            self._cache.pop(record.path, None)
            entry = self._load(target)
            if entry is None:
                raise AccountStoreError("Не удалось переименовать аккаунт.")
            return entry[0]

    def delete(self, record: AccountRecord) -> Path:
        """Move the account to ``_trash/`` instead of erasing it; returns the new location."""
        with self._lock:
            if not record.path.exists():
                raise AccountStoreError("Аккаунт уже удалён.")
            trash = self._directory / TRASH_DIRECTORY
            trash.mkdir(exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            destination = trash / f"{record.name} {stamp}.json.bak"
            record.path.replace(destination)
            self._cache.pop(record.path, None)
            return destination

    def _path_for(self, safe_name: str) -> Path:
        path = self._directory / f"{safe_name}.json"
        if path.resolve().parent != self._directory.resolve():
            raise AccountStoreError("Недопустимое имя аккаунта.")
        # Keep the existing spelling when only the letter case differs (Windows is case-insensitive).
        existing = next(
            (item for item in self._directory.glob("*.json") if item.stem.casefold() == safe_name.casefold()),
            None,
        )
        return existing or path
