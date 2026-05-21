import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .memory import JsonlMemory


@dataclass
class ToolContext:
    workspace_root: Path
    memory: JsonlMemory | None = None


ToolHandler = Callable[[ToolContext, dict[str, Any]], Any]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def names(self) -> set[str]:
        return set(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def run(self, name: str, context: ToolContext, arguments: dict[str, Any]) -> Any:
        if name not in self._tools:
            raise KeyError(f"unknown tool: {name}")
        return self._tools[name].handler(context, arguments)


def _resolve_inside_workspace(root: Path, requested: str) -> Path:
    candidate = Path(requested)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not (resolved == root or root in resolved.parents):
        raise PermissionError(f"path escapes workspace: {requested}")
    return resolved


def _relative(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def list_files(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    root = context.workspace_root.resolve()
    requested = arguments.get("path", ".")
    base = _resolve_inside_workspace(root, requested)
    if not base.exists():
        raise FileNotFoundError(requested)
    if not base.is_dir():
        raise NotADirectoryError(requested)

    files = []
    for path in sorted(base.rglob("*")):
        if path.is_file():
            files.append(_relative(path, root))

    return {"path": _relative(base, root) if base != root else ".", "files": files}


def read_file(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    root = context.workspace_root.resolve()
    path = _resolve_inside_workspace(root, arguments["path"])
    if not path.exists():
        raise FileNotFoundError(arguments["path"])
    if not path.is_file():
        raise IsADirectoryError(arguments["path"])

    max_chars = int(arguments.get("max_chars", 12000))
    content = path.read_text(encoding="utf-8")[:max_chars]
    return {
        "path": _relative(path, root),
        "content": content,
        "truncated": len(content) >= max_chars,
    }


def write_file(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    root = context.workspace_root.resolve()
    path = _resolve_inside_workspace(root, arguments["path"])
    outputs = (root / "outputs").resolve()
    if not (path == outputs or outputs in path.parents):
        raise PermissionError(f"write path must be inside outputs/: {arguments['path']}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(arguments.get("content", ""), encoding="utf-8")
    return {"path": _relative(path, root), "bytes_written": path.stat().st_size}


def inspect_csv(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    root = context.workspace_root.resolve()
    path = _resolve_inside_workspace(root, arguments["path"])
    if path.suffix.lower() != ".csv":
        raise ValueError("inspect_csv only supports .csv files")

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        columns = reader.fieldnames or []

    missing = {column: 0 for column in columns}
    numeric_values: dict[str, list[float]] = {column: [] for column in columns}
    numeric_failures = {column: 0 for column in columns}

    for row in rows:
        for column in columns:
            value = row.get(column, "")
            if value is None or value.strip() == "":
                missing[column] += 1
                continue
            try:
                numeric_values[column].append(float(value))
            except ValueError:
                numeric_failures[column] += 1

    numeric_ranges = {}
    for column, values in numeric_values.items():
        if values and numeric_failures[column] == 0:
            numeric_ranges[column] = {"min": min(values), "max": max(values)}

    return {
        "path": _relative(path, root),
        "rows": len(rows),
        "columns": columns,
        "missing_values": missing,
        "numeric_ranges": numeric_ranges,
    }


def remember(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    if context.memory is None:
        raise RuntimeError("memory is not configured")
    record = context.memory.remember(arguments["key"], arguments["value"])
    return {
        "key": record.key,
        "value": record.value,
        "created_at_unix": record.created_at_unix,
    }


def recall(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    if context.memory is None:
        raise RuntimeError("memory is not configured")
    query = arguments.get("query", "")
    records = context.memory.search(query) if query else context.memory.all()
    return {"records": [record.__dict__ for record in records]}


def create_default_tools() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="list_files",
            description="List files inside the workspace.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "default": "."}},
                "required": [],
            },
            handler=list_files,
        )
    )
    registry.register(
        Tool(
            name="read_file",
            description="Read a text file inside the workspace.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_chars": {"type": "integer", "default": 12000},
                },
                "required": ["path"],
            },
            handler=read_file,
        )
    )
    registry.register(
        Tool(
            name="write_file",
            description="Write a text file under outputs/.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            handler=write_file,
        )
    )
    registry.register(
        Tool(
            name="inspect_csv",
            description="Inspect a CSV file inside the workspace.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            handler=inspect_csv,
        )
    )
    registry.register(
        Tool(
            name="remember",
            description="Persist a key/value memory record.",
            parameters={
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": {},
                },
                "required": ["key", "value"],
            },
            handler=remember,
        )
    )
    registry.register(
        Tool(
            name="recall",
            description="Search persisted memory records.",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": [],
            },
            handler=recall,
        )
    )
    return registry


def serialize_tool_result(result: Any) -> str:
    return json.dumps(result, indent=2, sort_keys=True)

