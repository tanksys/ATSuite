import json
from pathlib import Path
from typing import Any, Iterable

from atsuite_sdk.state import register_state_object


class ClaudeCodeReviewState:
    def __init__(self) -> None:
        self.data_dir = ""
        self.repo_root = ""
        self.repo_fixture: dict[str, Any] = {}
        self.pull_requests: dict[str, dict[str, Any]] = {}

        self._module_dir = Path(__file__).resolve().parent
        self._candidate_data_dirs_override: list[Path] | None = None
        self.reload()

    def set_candidate_data_dirs(self, candidates: Iterable[Path]) -> None:
        self._candidate_data_dirs_override = [Path(candidate).resolve() for candidate in candidates]
        self.reload()

    def candidate_data_dirs(self) -> list[Path]:
        if self._candidate_data_dirs_override is not None:
            return list(self._candidate_data_dirs_override)
        candidates = [self._module_dir / "data"]
        if len(self._module_dir.parents) > 1:
            candidates.append(self._module_dir.parents[1] / "data")
        return candidates

    def data_dir_path(self) -> Path:
        if not self.data_dir:
            self.reload()
        return Path(self.data_dir)

    def repo_root_path(self) -> Path:
        if not self.data_dir:
            self.reload()

        repo_root = Path(self.repo_root) if self.repo_root else (Path(self.data_dir) / "fixture_repo").resolve()
        if (repo_root / ".git").exists():
            self.repo_root = str(repo_root)
            return repo_root
        raise FileNotFoundError(
            f"Packaged fixture repo not found at {repo_root}. Run the node init.sh during build."
        )

    def require_pr(self, pr_id: int) -> dict[str, Any]:
        key = str(pr_id)
        self.repo_root_path()
        if key not in self.pull_requests:
            raise KeyError(f"Unknown pull request id: {pr_id}")
        return self.pull_requests[key]

    def reload(self) -> None:
        data_dir = self._resolve_data_dir()
        repo_root = (data_dir / "fixture_repo").resolve()

        pr_payload = self._load_json(data_dir / "pr_fixture.json")
        self.data_dir = str(data_dir.resolve())
        self.repo_root = str(repo_root) if (repo_root / ".git").exists() else ""
        self.repo_fixture = self._load_json(data_dir / "repo_fixture.json")
        self.pull_requests = {
            str(pr["id"]): pr
            for pr in pr_payload.get("pull_requests", [])
        }

    def _resolve_data_dir(self) -> Path:
        for candidate in self.candidate_data_dirs():
            if (candidate / "repo_fixture.json").exists() and (candidate / "pr_fixture.json").exists():
                return candidate.resolve()
        raise FileNotFoundError(
            "repo_fixture.json and pr_fixture.json not found for ClaudeCodeReview state"
        )

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Expected JSON object in {path}")
        return payload


# The module name is intentionally identical in both node directories.
# MCP loading reuses the first-imported module via sys.modules, while FaaS
# targets still load their local copy in separate processes.
CLAUDE_CODE_REVIEW_STATE = ClaudeCodeReviewState()
register_state_object("claude_code_review_state", CLAUDE_CODE_REVIEW_STATE)
