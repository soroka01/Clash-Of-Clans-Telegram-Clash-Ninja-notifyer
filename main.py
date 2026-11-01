from __future__ import annotations

import asyncio
import logging
import sys

from app.application import Application
from app.logging_setup import LoggingConfigurator


def main() -> int:
    LoggingConfigurator().configure()
    try:
        application = Application.from_config()
    except RuntimeError as error:  # configuration problems are reported in plain words, without a traceback
        logging.getLogger("main").error("%s", error)
        return 1
    try:
        asyncio.run(application.run())
    except (KeyboardInterrupt, SystemExit):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
