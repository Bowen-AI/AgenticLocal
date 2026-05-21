#!/usr/bin/env python3
"""Build dependency-free release artifacts for agentic-loop.

The project is a pure-Python package with no runtime dependencies, so this
script can produce a valid wheel and source tarball using only the standard
library. That keeps local packaging usable on lean Linux/macOS systems where
pip, wheel, or python-build may not be installed yet.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
import tarfile
import zipfile
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def main() -> int:
    project = _project_metadata()
    name = project["name"]
    version = project["version"]
    wheel_name = f"{_wheel_dist_name(name)}-{version}-py3-none-any.whl"
    sdist_name = f"{name}-{version}.tar.gz"

    DIST.mkdir(exist_ok=True)
    wheel_path = DIST / wheel_name
    sdist_path = DIST / sdist_name

    _build_wheel(project, wheel_path)
    _build_sdist(project, sdist_path)

    print(f"built {wheel_path.relative_to(ROOT)}")
    print(f"built {sdist_path.relative_to(ROOT)}")
    return 0


def _project_metadata() -> dict:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]


def _wheel_dist_name(name: str) -> str:
    return name.replace("-", "_").replace(".", "_")


def _metadata_text(project: dict) -> str:
    classifiers = "".join(f"Classifier: {item}\n" for item in project.get("classifiers", []))
    authors = project.get("authors") or []
    author = authors[0].get("name", "") if authors else ""
    readme = (ROOT / project.get("readme", "README.md")).read_text(encoding="utf-8")
    return (
        "Metadata-Version: 2.1\n"
        f"Name: {project['name']}\n"
        f"Version: {project['version']}\n"
        f"Summary: {project.get('description', '')}\n"
        f"Author: {author}\n"
        f"Requires-Python: {project.get('requires-python', '')}\n"
        f"{classifiers}"
        "Description-Content-Type: text/markdown\n"
        "\n"
        f"{readme}\n"
    )


def _build_wheel(project: dict, wheel_path: Path) -> None:
    dist_info = f"{_wheel_dist_name(project['name'])}-{project['version']}.dist-info"
    files: dict[str, bytes] = {}

    for path in _package_files():
        arcname = path.relative_to(ROOT).as_posix()
        files[arcname] = path.read_bytes()

    files[f"{dist_info}/METADATA"] = _metadata_text(project).encode("utf-8")
    files[f"{dist_info}/WHEEL"] = (
        "Wheel-Version: 1.0\n"
        "Generator: agentic-loop package_release.py\n"
        "Root-Is-Purelib: true\n"
        "Tag: py3-none-any\n"
        "\n"
    ).encode("utf-8")
    files[f"{dist_info}/entry_points.txt"] = (
        "[console_scripts]\n"
        "agentic-loop = agentic_loop.cli:main\n"
    ).encode("utf-8")

    record_name = f"{dist_info}/RECORD"
    rows = []
    for arcname, content in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode("ascii")
        rows.append([arcname, f"sha256={digest}", str(len(content))])
    rows.append([record_name, "", ""])
    files[record_name] = _csv_bytes(rows)

    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for arcname in sorted(files):
            archive.writestr(arcname, files[arcname])


def _build_sdist(project: dict, sdist_path: Path) -> None:
    root_name = f"{project['name']}-{project['version']}"
    with tarfile.open(sdist_path, "w:gz") as archive:
        for path in _sdist_files():
            arcname = f"{root_name}/{path.relative_to(ROOT).as_posix()}"
            archive.add(path, arcname=arcname, recursive=False)


def _csv_bytes(rows: list[list[str]]) -> bytes:
    handle = io.StringIO(newline="")
    writer = csv.writer(handle)
    writer.writerows(rows)
    return handle.getvalue().encode("utf-8")


def _package_files() -> list[Path]:
    return sorted(
        path
        for path in (ROOT / "agentic_loop").rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _sdist_files() -> list[Path]:
    candidates = [
        ROOT / "pyproject.toml",
        ROOT / "README.md",
        ROOT / "CHANGELOG.md",
        ROOT / ".gitignore",
    ]
    for dirname in ("agentic_loop", "tests", "scripts", "docs", "sample_workspace"):
        candidates.extend(
            path
            for path in (ROOT / dirname).rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and not path.name.endswith(".pyc")
        )
    return sorted(path for path in candidates if path.exists() and _is_release_file(path))


def _is_release_file(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    ignored_parts = {"dist", "build", ".agentic", ".git", ".pytest_cache", "__pycache__"}
    if any(part in ignored_parts for part in rel.parts):
        return False
    if rel.parts[:2] == ("sample_workspace", "outputs") and path.name != ".gitkeep":
        return False
    if path.suffix in {".pyc", ".pyo"}:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
