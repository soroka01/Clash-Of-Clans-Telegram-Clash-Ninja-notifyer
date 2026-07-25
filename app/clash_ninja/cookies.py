from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:  # pragma: no cover - optional dependency
    AESGCM = None


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _windows_decrypt(data: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Авто-поиск cookie через AppData поддерживается только на Windows")

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    in_buffer = ctypes.create_string_buffer(data)
    in_blob = _DATA_BLOB(len(data), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_byte)))
    out_blob = _DATA_BLOB()

    if not crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    ):
        raise ctypes.WinError()

    try:
        result = ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)
    return result


def _load_local_state_master_key(local_state_path: Path) -> bytes | None:
    if not local_state_path.exists():
        return None
    try:
        payload = json.loads(local_state_path.read_text(encoding="utf-8"))
        encrypted_key = payload["os_crypt"]["encrypted_key"]
    except (OSError, KeyError, json.JSONDecodeError):
        return None

    key_bytes = base64.b64decode(encrypted_key)
    if key_bytes.startswith(b"DPAPI"):
        key_bytes = key_bytes[5:]
    return _windows_decrypt(key_bytes)


def _find_local_state_path(cookie_db_path: Path) -> Path | None:
    for ancestor in cookie_db_path.parents:
        candidate = ancestor / "Local State"
        if candidate.exists():
            return candidate
    return None


def _decrypt_cookie_value(encrypted_value: bytes, master_key: bytes | None) -> str:
    if encrypted_value.startswith(b"v10") or encrypted_value.startswith(b"v11"):
        payload = encrypted_value[3:]
        if master_key and AESGCM is not None:
            nonce = payload[:12]
            ciphertext = payload[12:]
            plaintext = AESGCM(master_key).decrypt(nonce, ciphertext, None)
            # Chromium prepends a 32-byte host hash to cookie values.
            if len(plaintext) > 32 and all(32 <= byte < 127 for byte in plaintext[32:]):
                plaintext = plaintext[32:]
            return plaintext.decode("utf-8", errors="replace")
        # Fallback for older Chromium builds or when the AES helper is unavailable.
        plaintext = _windows_decrypt(payload)
        if len(plaintext) > 32 and all(32 <= byte < 127 for byte in plaintext[32:]):
            plaintext = plaintext[32:]
        return plaintext.decode("utf-8", errors="replace")

    plaintext = _windows_decrypt(encrypted_value)
    return plaintext.decode("utf-8", errors="replace")


def _candidate_cookie_db_paths() -> list[Path]:
    local_app_data = os.environ.get("LOCALAPPDATA")
    app_data = os.environ.get("APPDATA")
    if not local_app_data and not app_data:
        return []

    browser_roots = [
        Path(local_app_data) / "Google" / "Chrome" / "User Data" if local_app_data else None,
        Path(local_app_data) / "Microsoft" / "Edge" / "User Data" if local_app_data else None,
        Path(local_app_data) / "BraveSoftware" / "Brave-Browser" / "User Data" if local_app_data else None,
        Path(app_data) / "Opera Software" / "Opera Stable" if app_data else None,
        Path(app_data) / "Opera Software" / "Opera GX Stable" if app_data else None,
    ]

    profiles = ("Default", "Profile 1", "Profile 2", "Profile 3", "Profile 4", "Profile 5", "Guest Profile")
    db_candidates: list[Path] = []
    for root in browser_roots:
        if not root or not root.exists():
            continue
        for profile in profiles:
            db_candidates.append(root / profile / "Network" / "Cookies")
            db_candidates.append(root / profile / "Cookies")
        db_candidates.append(root / "Network" / "Cookies")
        db_candidates.append(root / "Cookies")
    return [candidate for candidate in db_candidates if candidate.exists()]


def _copy_sqlite_database(source: Path) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="clash_ninja_cookies_"))
    target = temp_dir / "Cookies"
    try:
        shutil.copy2(source, target)
    except PermissionError as error:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError(
            f"Cookie DB заблокирована браузером: {source}. Закройте браузер и запустите бота ещё раз."
        ) from error
    return target


def _build_cookie_header_from_db(db_path: Path, domain_suffix: str) -> str | None:
    copied_db = _copy_sqlite_database(db_path)
    local_state_path = _find_local_state_path(db_path)
    master_key = _load_local_state_master_key(local_state_path) if local_state_path else None

    try:
        with sqlite3.connect(copied_db) as connection:
            rows = connection.execute(
                """
                SELECT host_key, name, encrypted_value, value
                FROM cookies
                WHERE host_key LIKE ?
                ORDER BY LENGTH(path) DESC, name
                """,
                (f"%{domain_suffix}",),
            ).fetchall()
    finally:
        shutil.rmtree(copied_db.parent, ignore_errors=True)

    if not rows:
        return None

    cookies: list[str] = []
    for host_key, name, encrypted_value, value in rows:
        if encrypted_value:
            try:
                cookie_value = _decrypt_cookie_value(encrypted_value, master_key)
            except Exception as error:  # noqa: BLE001 - best-effort fallback
                logger.debug("Не удалось расшифровать cookie %s для %s: %s", name, host_key, error)
                continue
        else:
            cookie_value = value or ""
        if not name or cookie_value == "":
            continue
        if any(ord(character) < 0x20 or ord(character) == 0x7F for character in cookie_value):
            logger.debug("Пропущен cookie %s: значение содержит управляющие символы", name)
            continue
        cookies.append(f"{name}={cookie_value}")

    if not cookies:
        return None
    return "; ".join(cookies)


def discover_cookie_header(domain_suffix: str = "clash.ninja") -> str | None:
    """Try to reconstruct the HTTP Cookie header from Chromium/Opera profiles in AppData."""
    for db_path in _candidate_cookie_db_paths():
        try:
            header = _build_cookie_header_from_db(db_path, domain_suffix)
        except Exception as error:  # noqa: BLE001 - best-effort fallback
            logger.debug("Не удалось прочитать cookie DB %s: %s", db_path, error)
            continue
        if header:
            logger.info("Cookie Clash Ninja найден в %s", db_path)
            return header
    return None
