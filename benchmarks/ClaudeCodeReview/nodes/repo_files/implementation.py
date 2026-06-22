from pathlib import Path
import re
from typing import Any

from atsuite_sdk.abstract import registry
from claude_code_review_state import CLAUDE_CODE_REVIEW_STATE


_TODO_ALLOWED = {"pending", "in_progress", "completed"}


def _ensure_repo() -> Path:
    return CLAUDE_CODE_REVIEW_STATE.repo_root_path()


def _safe_path(path: str) -> Path:
    repo_root = _ensure_repo().resolve()
    candidate = (repo_root / path).resolve()
    if candidate != repo_root and repo_root not in candidate.parents:
        raise ValueError(f"Path escapes fixture repo: {path}")
    return candidate


def _iter_repo_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(root)
        if ".git" in rel_path.parts:
            continue
        yield path


def _matches_glob(path_value: str, pattern: str) -> bool:
    normalized = path_value.replace("\\", "/")
    candidate = Path(normalized)
    if candidate.match(pattern):
        return True
    if pattern.startswith("**/") and candidate.match(pattern[3:]):
        return True
    return False


def _normalize_line_window(offset: int, limit: int, total_lines: int) -> tuple[int, int]:
    start = max(1, offset)
    if total_lines == 0:
        return (1, 0)
    end = min(total_lines, start + max(1, limit) - 1)
    return (start, end)


@registry.tool()
def ls(path: str = ".", max_entries: int = 200) -> dict[str, Any]:
    """List files in the deterministic Claude Code review fixture repository."""
    repo_root = _ensure_repo().resolve()
    target = _safe_path(path)
    entries = []

    if target.is_file():
        rel_path = str(target.relative_to(repo_root))
        entries.append({"path": rel_path, "type": "file"})
    else:
        for current in sorted(target.rglob("*")):
            rel_path = current.relative_to(repo_root)
            if ".git" in rel_path.parts:
                continue
            entries.append(
                {
                    "path": str(rel_path),
                    "type": "dir" if current.is_dir() else "file",
                }
            )
            if len(entries) >= max_entries:
                break

    return {"root": path, "entries": entries}


@registry.tool()
def glob_files(pattern: str, path: str = ".", max_results: int = 200) -> dict[str, Any]:
    """Match files with a glob pattern inside the fixture repository."""
    repo_root = _ensure_repo()
    base = _safe_path(path)
    matches: list[str] = []

    for file_path in _iter_repo_files(repo_root):
        try:
            file_path.relative_to(base)
        except ValueError:
            continue
        rel_path = str(file_path.relative_to(repo_root))
        relative_to_base = str(file_path.relative_to(base))
        if _matches_glob(relative_to_base, pattern) or _matches_glob(rel_path, pattern):
            matches.append(rel_path)
            if len(matches) >= max_results:
                break

    return {"pattern": pattern, "path": path, "matches": matches}


@registry.tool()
def grep_text(
    pattern: str,
    path: str = ".",
    glob: str = "**/*",
    max_results: int = 50,
) -> dict[str, Any]:
    """Search text in repository files using a regular expression."""
    repo_root = _ensure_repo()
    base = _safe_path(path)
    regex = re.compile(pattern, re.IGNORECASE)
    matches = []

    for file_path in _iter_repo_files(repo_root):
        try:
            file_path.relative_to(base)
        except ValueError:
            continue
        rel_path = str(file_path.relative_to(repo_root))
        relative_to_base = str(file_path.relative_to(base))
        if not (_matches_glob(relative_to_base, glob) or _matches_glob(rel_path, glob)):
            continue
        for line_number, line in enumerate(
            file_path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not regex.search(line):
                continue
            matches.append(
                {
                    "path": rel_path,
                    "line": line_number,
                    "excerpt": line.strip(),
                }
            )
            if len(matches) >= max_results:
                return {
                    "pattern": pattern,
                    "path": path,
                    "glob": glob,
                    "matches": matches,
                }

    return {"pattern": pattern, "path": path, "glob": glob, "matches": matches}


@registry.tool()
def read_file(path: str, offset: int = 1, limit: int = 200) -> dict[str, Any]:
    """Read file content with line numbers from the fixture repository."""
    target = _safe_path(path)
    if not target.is_file():
        raise FileNotFoundError(path)

    lines = target.read_text(encoding="utf-8").splitlines()
    start_line, end_line = _normalize_line_window(offset, limit, len(lines))
    content = "\n".join(lines[start_line - 1 : end_line]) if end_line else ""
    return {
        "path": path,
        "start_line": start_line,
        "end_line": end_line,
        "content": content,
    }


@registry.tool()
def todo_write(todos: list[dict[str, str]]) -> dict[str, Any]:
    """Store the current review checklist snapshot."""
    normalized = []
    by_status = {status: 0 for status in sorted(_TODO_ALLOWED)}
    for index, todo in enumerate(todos):
        content = str(todo.get("content", "")).strip()
        if not content:
            raise ValueError(f"Todo item {index} is missing content")
        status = str(todo.get("status", "pending")).strip().lower()
        if status not in _TODO_ALLOWED:
            raise ValueError(f"Unsupported todo status: {status}")
        normalized.append({"content": content, "status": status})
        by_status[status] += 1

    return {
        "todos": normalized,
        "total": len(normalized),
        "by_status": by_status,
    }
