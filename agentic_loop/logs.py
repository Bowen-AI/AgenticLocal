import json
import time
from pathlib import Path
from typing import Any

from .storage import SQLiteStore


class JsonlTraceLogger:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        event_type: str,
        payload: dict[str, Any],
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        if not self.path:
            return
        event = {
            "event_type": event_type,
            "created_at_unix": time.time(),
            "session_id": session_id,
            "run_id": run_id,
            "payload": payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")


class SQLiteTraceLogger:
    def __init__(self, storage: SQLiteStore):
        self.storage = storage

    def log(
        self,
        event_type: str,
        payload: dict[str, Any],
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        self.storage.record_event(event_type, payload, session_id=session_id, run_id=run_id)


class CompositeTraceLogger:
    def __init__(self, *loggers):
        self.loggers = [logger for logger in loggers if logger is not None]

    def log(
        self,
        event_type: str,
        payload: dict[str, Any],
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        for logger in self.loggers:
            logger.log(event_type, payload, session_id=session_id, run_id=run_id)
