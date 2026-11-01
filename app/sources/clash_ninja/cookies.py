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

_PROFILES = ("Default", "Profile 1", "Profile 2", "Profile 3", "Profile 4", "Profile 5", "Guest Profile")


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_byte))]


class WindowsDpapi:
    """Thin wrapper over CryptUnprotectData."""

    @staticmethod
    def unprotect(data: bytes) -> bytes:
        if os.name != "nt":
            raise RuntimeError("Авто-поиск cookie через AppData поддерживается только на Windows")

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32

        in_buffer = ctypes.create_string_buffer(data)
        in_blob = _DataBlob(len(data), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_byte)))
        out_blob = _DataBlob()

        if not crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
            raise ctypes.WinError()

        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)


class CookieDiscoverer:
    """Rebuilds the HTTP Cookie header for a site from Chromium/Opera profiles in AppData."""

    def __init__(self, domain_suffix: str = "clash.ninja", dpapi: WindowsDpapi | None = None) -> None:
        self._domain_suffix = domain_suffix
        self._dpapi = dpapi or WindowsDpapi()

    def discover(self) -> str | None:
        for db_path in self._candidate_cookie_db_paths():
            try:
                header = self._build_cookie_header_from_db(db_path)
            except Exception as error:  # noqa: BLE001 - best-effort fallback
                logger.debug("Не удалось прочитать cookie DB %s: %s", db_path, error)
                continue
            if header:
                logger.info("Cookie Clash Ninja найден в %s", db_path)
                return header
        return None

    # ----- locating browser profiles -----------------------------------------------

    @staticmethod
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

        db_candidates: list[Path] = []
        for root in browser_roots:
            if not root or not root.exists():
                continue
            for profile in _PROFILES:
                db_candidates.append(root / profile / "Network" / "Cookies")
                db_candidates.append(root / profile / "Cookies")
            db_candidates.append(root / "Network" / "Cookies")
            db_candidates.append(root / "Cookies")
        return [candidate for candidate in db_candidates if candidate.exists()]

    @staticmethod
    def _find_local_state_path(cookie_db_path: Path) -> Path | None:
        for ancestor in cookie_db_path.parents:
            candidate = ancestor / "Local State"
            if candidate.exists():
                return candidate
        return None

    @staticmethod
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

    # ----- decryption --------------------------------------------------------------

    def _load_local_state_master_key(self, local_state_path: Path) -> bytes | None:
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
        return self._dpapi.unprotect(key_bytes)

    @staticmethod
    def _strip_host_hash(plaintext: bytes) -> bytes:
        # Chromium prepends a 32-byte host hash to cookie values.
        if len(plaintext) > 32 and all(32 <= byte < 127 for byte in plaintext[32:]):
            return plaintext[32:]
        return plaintext

    def _decrypt_cookie_value(self, encrypted_value: bytes, master_key: bytes | None) -> str:
        if encrypted_value.startswith(b"v10") or encrypted_value.startswith(b"v11"):
            payload = encrypted_value[3:]
            if master_key and AESGCM is not None:
                nonce = payload[:12]
                ciphertext = payload[12:]
                plaintext = AESGCM(master_key).decrypt(nonce, ciphertext, None)
                return self._strip_host_hash(plaintext).decode("utf-8", errors="replace")
            # Fallback for older Chromium builds or when the AES helper is unavailable.
            plaintext = self._dpapi.unprotect(payload)
            return self._strip_host_hash(plaintext).decode("utf-8", errors="replace")

        plaintext = self._dpapi.unprotect(encrypted_value)
        return plaintext.decode("utf-8", errors="replace")

    def _build_cookie_header_from_db(self, db_path: Path) -> str | None:
        copied_db = self._copy_sqlite_database(db_path)
        local_state_path = self._find_local_state_path(db_path)
        master_key = self._load_local_state_master_key(local_state_path) if local_state_path else None

        try:
            with sqlite3.connect(copied_db) as connection:
                rows = connection.execute(
                    """
                    SELECT host_key, name, encrypted_value, value
                    FROM cookies
                    WHERE host_key LIKE ?
                    ORDER BY LENGTH(path) DESC, name
                    """,
                    (f"%{self._domain_suffix}",),
                ).fetchall()
        finally:
            shutil.rmtree(copied_db.parent, ignore_errors=True)

        if not rows:
            return None

        cookies: list[str] = []
        for host_key, name, encrypted_value, value in rows:
            if encrypted_value:
                try:
                    cookie_value = self._decrypt_cookie_value(encrypted_value, master_key)
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

        return "; ".join(cookies) if cookies else None
