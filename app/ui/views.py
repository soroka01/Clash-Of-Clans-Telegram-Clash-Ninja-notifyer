from __future__ import annotations

import re
from dataclasses import dataclass, replace

# View kinds. The serialized form is stored in SQLite (menu state) and inside callback_data of
# buttons that stay in chat history, so existing spellings must keep working:
#   main | settings | tz | all | sorted | v:<village id> | accounts | a:<village id> | del:<village id>
#   | import | import:<village id of the account being replaced> | help
# Pageable views take an "@<page>" suffix (zero based): all@1, v:ABC@2.
MAIN = "main"
SETTINGS = "settings"
TIMEZONE = "tz"
ALL = "all"
SORTED = "sorted"
VILLAGE = "v"
ACCOUNTS = "accounts"
ACCOUNT = "a"
CONFIRM_DELETE = "del"
IMPORT = "import"
HELP = "help"

_WITH_ARGUMENT = {VILLAGE, ACCOUNT, CONFIRM_DELETE, IMPORT}
_PAGEABLE = {ALL, SORTED, VILLAGE}
_SIMPLE = {MAIN, SETTINGS, TIMEZONE, ALL, SORTED, ACCOUNTS, IMPORT, HELP}
_PAGE_SUFFIX = re.compile(r"^(?P<body>.*?)(?:@(?P<page>\d{1,4}))?$", re.DOTALL)


@dataclass(frozen=True, slots=True)
class ViewState:
    kind: str = MAIN
    argument: str | None = None
    page: int = 0

    @classmethod
    def parse(cls, raw: str | None) -> "ViewState":
        """Tolerant parser: anything unknown (or from an older version) falls back to the all-accounts list."""
        text = (raw or "").strip()
        match = _PAGE_SUFFIX.match(text)
        body, page = (match.group("body"), int(match.group("page") or 0)) if match else (text, 0)
        kind, _, argument = body.partition(":")
        if kind in _WITH_ARGUMENT and argument:
            return cls(kind, argument, page if kind in _PAGEABLE else 0)
        if kind in _SIMPLE:
            return cls(kind, None, page if kind in _PAGEABLE else 0)
        return cls(ALL)

    def serialize(self) -> str:
        body = f"{self.kind}:{self.argument}" if self.argument else self.kind
        return f"{body}@{self.page}" if self.page and self.kind in _PAGEABLE else body

    def with_page(self, page: int) -> "ViewState":
        return replace(self, page=max(0, page))

    @property
    def callback(self) -> str:
        return f"view:{self.serialize()}"

    @property
    def is_dashboard(self) -> bool:
        return self.kind in _PAGEABLE

    @classmethod
    def village(cls, village_id: str, page: int = 0) -> "ViewState":
        return cls(VILLAGE, village_id, page)

    @classmethod
    def account(cls, village_id: str) -> "ViewState":
        return cls(ACCOUNT, village_id)

    @classmethod
    def import_for(cls, village_id: str | None = None) -> "ViewState":
        return cls(IMPORT, village_id)

    @classmethod
    def confirm_delete(cls, village_id: str) -> "ViewState":
        return cls(CONFIRM_DELETE, village_id)
