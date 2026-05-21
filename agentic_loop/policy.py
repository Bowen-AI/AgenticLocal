from dataclasses import dataclass, field
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


def _as_paths(values: list[str | Path] | tuple[str | Path, ...]) -> tuple[Path, ...]:
    return tuple(Path(value) for value in values)


@dataclass
class WorkspaceAccessConfig:
    workspace_root: Path
    read_roots: tuple[Path, ...] = field(default_factory=lambda: (Path("."),))
    write_roots: tuple[Path, ...] = field(default_factory=lambda: (Path("outputs"),))
    approval_required_roots: tuple[Path, ...] = field(default_factory=tuple)

    def __init__(
        self,
        workspace_root: str | Path,
        read_roots: list[str | Path] | tuple[str | Path, ...] | None = None,
        write_roots: list[str | Path] | tuple[str | Path, ...] | None = None,
        approval_required_roots: list[str | Path] | tuple[str | Path, ...] | None = None,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.read_roots = _as_paths(read_roots or (".",))
        self.write_roots = _as_paths(write_roots or ("outputs",))
        self.approval_required_roots = _as_paths(approval_required_roots or ())
        self._resolved_read_roots = self._resolve_roots(self.read_roots, "read")
        self._resolved_write_roots = self._resolve_roots(self.write_roots, "write")
        self._resolved_approval_roots = self._resolve_roots(
            self.approval_required_roots,
            "approval",
        )

    def _resolve_roots(self, roots: tuple[Path, ...], label: str) -> tuple[Path, ...]:
        resolved = []
        for root in roots:
            try:
                resolved.append(self.resolve_workspace_path(root))
            except PermissionError as exc:
                raise ValueError(f"{label} root escapes workspace: {root}") from exc
        return tuple(resolved)

    def resolve_workspace_path(self, path: str | Path) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate
        resolved = candidate.resolve()
        if not self._contains(self.workspace_root, resolved):
            raise PermissionError(f"path escapes workspace: {path}")
        return resolved

    def allows_read(self, path: str | Path) -> bool:
        resolved = self.resolve_workspace_path(path)
        return any(self._contains(root, resolved) for root in self._resolved_read_roots)

    def allows_write(self, path: str | Path) -> bool:
        resolved = self.resolve_workspace_path(path)
        return any(self._contains(root, resolved) for root in self._resolved_write_roots)

    def requires_approval(self, path: str | Path) -> bool:
        resolved = self.resolve_workspace_path(path)
        return any(self._contains(root, resolved) for root in self._resolved_approval_roots)

    def write_root_labels(self) -> list[str]:
        return [self._label(root) for root in self._resolved_write_roots]

    def read_root_labels(self) -> list[str]:
        return [self._label(root) for root in self._resolved_read_roots]

    def approval_root_labels(self) -> list[str]:
        return [self._label(root) for root in self._resolved_approval_roots]

    def _label(self, path: Path) -> str:
        if path == self.workspace_root:
            return "."
        return str(path.relative_to(self.workspace_root))

    def _contains(self, root: Path, path: Path) -> bool:
        return path == root or root in path.parents

    def describe(self) -> dict[str, Any]:
        return {
            "workspace_root": str(self.workspace_root),
            "read_roots": self.read_root_labels(),
            "write_roots": self.write_root_labels(),
            "approval_required_roots": self.approval_root_labels(),
        }


class WorkspacePolicy:
    def __init__(
        self,
        workspace_root: str | Path,
        allowed_tools: set[str] | None = None,
        outputs_dir_name: str = "outputs",
        access: WorkspaceAccessConfig | None = None,
        read_roots: list[str | Path] | tuple[str | Path, ...] | None = None,
        write_roots: list[str | Path] | tuple[str | Path, ...] | None = None,
        approval_required_roots: list[str | Path] | tuple[str | Path, ...] | None = None,
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
        if write_roots is None and outputs_dir_name != "outputs":
            write_roots = (outputs_dir_name,)
        self.access = access or WorkspaceAccessConfig(
            self.workspace_root,
            read_roots=read_roots,
            write_roots=write_roots,
            approval_required_roots=approval_required_roots,
        )

    def check(self, call: ToolCall) -> PolicyDecision:
        if call.name not in self.allowed_tools:
            return PolicyDecision(False, f"tool is not allowed: {call.name}")

        for arg_name in READ_PATH_ARGS.get(call.name, []):
            value = call.arguments.get(arg_name)
            if value is None:
                continue
            try:
                allowed = self.access.allows_read(value)
            except PermissionError as exc:
                return PolicyDecision(False, str(exc))
            if not allowed:
                roots = ", ".join(self.access.read_root_labels())
                return PolicyDecision(
                    False,
                    f"read path must be inside configured read roots ({roots}): {value}",
                )

        for arg_name in WRITE_PATH_ARGS.get(call.name, []):
            value = call.arguments.get(arg_name)
            if value is None:
                continue
            try:
                requires_approval = self.access.requires_approval(value)
                allowed = self.access.allows_write(value)
            except PermissionError as exc:
                return PolicyDecision(False, str(exc))
            if requires_approval:
                return PolicyDecision(
                    False,
                    f"write path requires approval: {value}",
                    requires_approval=True,
                )
            if not allowed:
                roots = ", ".join(self.access.write_root_labels())
                return PolicyDecision(
                    False,
                    f"write path must be inside configured write roots ({roots}): {value}",
                )

        return PolicyDecision(True, "allowed")

    def describe(self) -> dict[str, Any]:
        return {
            "allowed_tools": sorted(self.allowed_tools),
            **self.access.describe(),
        }
