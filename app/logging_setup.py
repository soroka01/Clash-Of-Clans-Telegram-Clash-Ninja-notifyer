from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DATE_FORMAT = "%d %H:%M:%S"
LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-15s | %(message)s"
_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_STD_OUTPUT_HANDLE = -11


class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\033[36m",
        logging.INFO: "\033[32m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[35m",
    }
    RESET = "\033[0m"

    def __init__(self, *args: object, use_colors: bool = True, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._use_colors = use_colors

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        if not self._use_colors:
            return message
        return f"{self.COLORS.get(record.levelno, '')}{message}{self.RESET}"


class LoggingConfigurator:
    """Console (INFO) plus rotating files: bot.log (everything) and error.log (errors only)."""

    def __init__(self, directory: Path = Path("logs")) -> None:
        self._directory = directory

    def configure(self) -> None:
        self._directory.mkdir(exist_ok=True)
        plain = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(ColorFormatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT, use_colors=self._console_supports_colors()))

        logging.basicConfig(
            level=logging.DEBUG,
            handlers=[console, self._rotating("bot.log", logging.DEBUG, plain), self._rotating("error.log", logging.ERROR, plain)],
        )
        logging.getLogger("aiohttp").setLevel(logging.WARNING)
        logging.getLogger("aiogram").setLevel(logging.WARNING)

    def _rotating(self, name: str, level: int, formatter: logging.Formatter) -> RotatingFileHandler:
        handler = RotatingFileHandler(self._directory / name, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
        handler.setLevel(level)
        handler.setFormatter(formatter)
        return handler

    @staticmethod
    def _console_supports_colors() -> bool:
        """Enable ANSI on supported Windows consoles; otherwise keep logs clean."""
        if not sys.stdout.isatty():
            return False
        if os.name != "nt":
            return True
        try:
            from ctypes import byref, c_uint, windll

            stdout_handle = windll.kernel32.GetStdHandle(_STD_OUTPUT_HANDLE)
            mode = c_uint()
            if not windll.kernel32.GetConsoleMode(stdout_handle, byref(mode)):
                return False
            return bool(windll.kernel32.SetConsoleMode(stdout_handle, mode.value | _ENABLE_VIRTUAL_TERMINAL_PROCESSING))
        except (ImportError, AttributeError, OSError):
            return False
