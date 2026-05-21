import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass
class MemoryRecord:
    key: str
    value: Any
    created_at_unix: float


class MemoryStore(Protocol):
    def remember(self, key: str, value: Any) -> MemoryRecord:
        ...

    def all(self) -> list[MemoryRecord]:
        ...

    def latest(self, key: str) -> MemoryRecord | None:
        ...

    def search(self, query: str, limit: int = 5) -> list[MemoryRecord]:
        ...


class JsonlMemory:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def remember(self, key: str, value: Any) -> MemoryRecord:
        record = MemoryRecord(key=key, value=value, created_at_unix=time.time())
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.__dict__, sort_keys=True) + "\n")
        return record

    def all(self) -> list[MemoryRecord]:
        if not self.path.exists():
            return []
        records = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                data = json.loads(stripped)
                records.append(MemoryRecord(**data))
        return records

    def latest(self, key: str) -> MemoryRecord | None:
        matches = [record for record in self.all() if record.key == key]
        return matches[-1] if matches else None

    def search(self, query: str, limit: int = 5) -> list[MemoryRecord]:
        query_lower = query.lower()
        matches = []
        for record in self.all():
            haystack = f"{record.key} {json.dumps(record.value, sort_keys=True)}".lower()
            if query_lower in haystack:
                matches.append(record)
        return matches[-limit:]
