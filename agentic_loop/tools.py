import csv
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol

from .memory import MemoryStore


class WebClient(Protocol):
    def get_json(self, url: str, timeout_s: float = 10.0) -> Any:
        ...

    def get_text(self, url: str, timeout_s: float = 10.0) -> str:
        ...


class UrllibWebClient:
    def get_json(self, url: str, timeout_s: float = 10.0) -> Any:
        text = self.get_text(url, timeout_s=timeout_s)
        return json.loads(text)

    def get_text(self, url: str, timeout_s: float = 10.0) -> str:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "agentic-loop/0.1"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            content_type = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(content_type, errors="replace")


@dataclass
class ToolContext:
    workspace_root: Path
    memory: MemoryStore | None = None
    web_client: WebClient | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


ToolHandler = Callable[[ToolContext, dict[str, Any]], Any]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    source: str = "local"
    risk_level: str = "low"
    ui_component_hint: str | None = None
    enabled: bool = True

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    def metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "schema": self.schema(),
            "description": self.description,
            "source": self.source,
            "risk_level": self.risk_level,
            "ui_component_hint": self.ui_component_hint,
            "enabled": self.enabled,
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

    def metadata(self) -> list[dict[str, Any]]:
        return [tool.metadata() for tool in self._tools.values()]

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


def current_datetime(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now().astimezone()
    return {
        "iso": now.isoformat(timespec="seconds"),
        "date": now.date().isoformat(),
        "time": now.strftime("%H:%M:%S"),
        "timezone": now.tzname() or "",
        "weekday": now.strftime("%A"),
    }


def _web_client(context: ToolContext) -> WebClient:
    return context.web_client or UrllibWebClient()


def _max_results(arguments: dict[str, Any], default: int = 5) -> int:
    return max(1, min(int(arguments.get("max_results", default)), 10))


def _flatten_duckduckgo_topics(topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for item in topics:
        if "Topics" in item:
            results.extend(_flatten_duckduckgo_topics(item.get("Topics") or []))
            continue
        title = item.get("Text") or item.get("FirstURL") or "Untitled result"
        results.append(
            {
                "title": str(title).split(" - ")[0],
                "url": item.get("FirstURL") or "",
                "snippet": item.get("Text") or "",
            }
        )
    return results


def _strip_html(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _duckduckgo_result_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    query = urllib.parse.parse_qs(parsed.query)
    if "uddg" in query:
        return query["uddg"][0]
    return value


def _search_duckduckgo_html(context: ToolContext, query: str, max_results: int) -> list[dict[str, Any]]:
    url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    html = _web_client(context).get_text(url)
    matches = re.findall(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    snippets = re.findall(
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>|<div[^>]+class="result__snippet"[^>]*>(.*?)</div>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    snippet_text = [_strip_html(left or right) for left, right in snippets]
    results = []
    for index, (href, title) in enumerate(matches[:max_results]):
        results.append(
            {
                "title": _strip_html(title),
                "url": _duckduckgo_result_url(href),
                "snippet": snippet_text[index] if index < len(snippet_text) else "",
            }
        )
    return results


def search_web(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    query = arguments["query"].strip()
    if not query:
        raise ValueError("search_web requires a non-empty query")
    max_results = _max_results(arguments)
    url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode(
        {
            "q": query,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1",
        }
    )
    data = _web_client(context).get_json(url)
    results = []
    if data.get("AbstractText"):
        results.append(
            {
                "title": data.get("Heading") or query,
                "url": data.get("AbstractURL") or data.get("AbstractSource") or "",
                "snippet": data.get("AbstractText") or "",
            }
        )
    results.extend(_flatten_duckduckgo_topics(data.get("RelatedTopics") or []))
    if not results:
        results = _search_duckduckgo_html(context, query, max_results)
    return {
        "query": query,
        "source": "DuckDuckGo",
        "results": results[:max_results],
        "result_count": min(len(results), max_results),
    }


def search_news(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    query = arguments["query"].strip()
    if not query:
        raise ValueError("search_news requires a non-empty query")
    max_results = _max_results(arguments)
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    )
    text = _web_client(context).get_text(url)
    root = ET.fromstring(text)
    results = []
    for item in root.findall("./channel/item")[:max_results]:
        source = item.find("source")
        results.append(
            {
                "title": item.findtext("title", default=""),
                "url": item.findtext("link", default=""),
                "published": item.findtext("pubDate", default=""),
                "source": source.text if source is not None else "",
            }
        )
    return {
        "query": query,
        "source": "Google News RSS",
        "results": results,
        "result_count": len(results),
    }


def fetch_url(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    url = arguments["url"].strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("fetch_url only supports http and https URLs")
    max_chars = int(arguments.get("max_chars", 12000))
    text = _web_client(context).get_text(url)
    title_match = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.IGNORECASE | re.DOTALL)
    title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"\s+", " ", body).strip()
    content = body[:max_chars]
    return {
        "url": url,
        "title": title,
        "content": content,
        "truncated": len(body) > max_chars,
    }


def create_default_tools(enable_network: bool = False) -> ToolRegistry:
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
            risk_level="low",
            ui_component_hint="file_browser",
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
            risk_level="low",
            ui_component_hint="text_preview",
        )
    )
    registry.register(
        Tool(
            name="write_file",
            description="Write a text file under configured writable workspace roots.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            handler=write_file,
            risk_level="medium",
            ui_component_hint="file_writer",
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
            risk_level="low",
            ui_component_hint="table_preview",
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
            risk_level="low",
            ui_component_hint="memory_view",
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
            risk_level="low",
            ui_component_hint="memory_view",
        )
    )
    registry.register(
        Tool(
            name="current_datetime",
            description="Return the current local date, time, weekday, and timezone.",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            handler=current_datetime,
            risk_level="low",
            ui_component_hint="status_banner",
        )
    )
    if enable_network:
        registry.register(
            Tool(
                name="search_web",
                description="Search the public web for general information.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer", "default": 5},
                    },
                    "required": ["query"],
                },
                handler=search_web,
                source="network",
                risk_level="medium",
                ui_component_hint="search_results",
            )
        )
        registry.register(
            Tool(
                name="search_news",
                description="Search current news headlines for a query.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer", "default": 5},
                    },
                    "required": ["query"],
                },
                handler=search_news,
                source="network",
                risk_level="medium",
                ui_component_hint="news_results",
            )
        )
        registry.register(
            Tool(
                name="fetch_url",
                description="Fetch and summarize text from a public HTTP or HTTPS URL.",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "max_chars": {"type": "integer", "default": 12000},
                    },
                    "required": ["url"],
                },
                handler=fetch_url,
                source="network",
                risk_level="medium",
                ui_component_hint="web_page",
            )
        )
    return registry


def serialize_tool_result(result: Any) -> str:
    return json.dumps(result, indent=2, sort_keys=True)
