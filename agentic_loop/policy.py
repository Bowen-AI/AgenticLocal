from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .types import PolicyDecision, ToolCall


READ_PATH_ARGS = {
    "list_files": ["path"],
    "read_file": ["path"],
    "inspect_csv": ["path"],
}

WRITE_PATH_ARGS = {
    "write_file": ["path"],
}


@dataclass
class WorkspacePolicy:
    workspace_root: Path
    allowed_tools: set[str]
    outputs_dir_name: str = "outputs"

    def __init__(
        self,
        workspace_root: str | Path,
        allowed_tools: set[str] | None = None,
        outputs_dir_name: str = "outputs",
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.allowed_tools = allowed_tools or {
            "list_files",
            "read_file",
            "write_file",
            "inspect_csv",
            "remember",
            "recall",
        }
        self.outputs_dir_name = outputs_dir_name

    def check(self, call: ToolCall) -> PolicyDecision:
        if call.name not in self.allowed_tools:
            return PolicyDecision(False, f"tool is not allowed: {call.name}")

        for arg_name in READ_PATH_ARGS.get(call.name, []):
            value = call.arguments.get(arg_name)
            if value is None:
                continue
            if not self._is_inside_workspace(value):
                return PolicyDecision(False, f"path escapes workspace: {value}")

        for arg_name in WRITE_PATH_ARGS.get(call.name, []):
            value = call.arguments.get(arg_name)
            if value is None:
                continue
            if not self._is_inside_outputs(value):
                return PolicyDecision(False, f"write path must be inside outputs/: {value}")

        return PolicyDecision(True, "allowed")

    def _resolve_candidate(self, path: str | Path) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate
        return candidate.resolve()

    def _is_inside_workspace(self, path: str | Path) -> bool:
        candidate = self._resolve_candidate(path)
        return candidate == self.workspace_root or self.workspace_root in candidate.parents

    def _is_inside_outputs(self, path: str | Path) -> bool:
        outputs = (self.workspace_root / self.outputs_dir_name).resolve()
        candidate = self._resolve_candidate(path)
        return candidate == outputs or outputs in candidate.parents

    def describe(self) -> dict[str, Any]:
        return {
            "workspace_root": str(self.workspace_root),
            "allowed_tools": sorted(self.allowed_tools),
            "outputs_dir_name": self.outputs_dir_name,
        }

