import logging
from collections import deque
from datetime import datetime, timezone

STARTED_AT = datetime.now(timezone.utc)


class ErrorBuffer(logging.Handler):
    def __init__(self, size: int = 20):
        super().__init__(level=logging.ERROR)
        self._items: deque[dict] = deque(maxlen=size)

    def emit(self, record: logging.LogRecord) -> None:
        exc = record.exc_info[1] if record.exc_info else None
        self._items.appendleft({
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "logger": record.name,
            "message": record.getMessage(),
            "error": repr(exc)[:300] if exc else "",
        })

    def records(self) -> list[dict]:
        return list(self._items)


def install() -> ErrorBuffer:
    handler = ErrorBuffer()
    logging.getLogger().addHandler(handler)
    return handler
