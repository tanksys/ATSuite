from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


STATELESS_ACCESS = "stateless"
VALID_ACCESS_MODES = {STATELESS_ACCESS, "r", "w", "rw"}


@dataclass(frozen=True)
class ToolAccess:
    domain: str = ""
    access: str = STATELESS_ACCESS

    @property
    def is_stateful(self) -> bool:
        return self.access != STATELESS_ACCESS and bool(self.domain)

    @classmethod
    def from_values(cls, domain: str = "", access: str = STATELESS_ACCESS) -> "ToolAccess":
        normalized = str(access or STATELESS_ACCESS).strip().lower()
        if normalized not in VALID_ACCESS_MODES:
            raise ValueError(f"Unsupported access mode: {access}")
        normalized_domain = str(domain or "").strip()
        if normalized == STATELESS_ACCESS:
            normalized_domain = ""
        return cls(domain=normalized_domain, access=normalized)


class AccessScheduler:
    """Client-side read/write lock table used only for FaaS replay."""

    def __init__(self, *, enabled: bool):
        self.enabled = bool(enabled)
        self._readers: Dict[str, int] = {}
        self._writers: set[str] = set()

    def can_start(self, access: ToolAccess) -> bool:
        if not self.enabled or not access.is_stateful:
            return True
        domain = access.domain
        if access.access == "r":
            return domain not in self._writers
        return domain not in self._writers and self._readers.get(domain, 0) == 0

    def start(self, access: ToolAccess) -> None:
        if not self.enabled or not access.is_stateful:
            return
        if not self.can_start(access):
            raise RuntimeError(f"Access conflict for domain {access.domain}")
        if access.access == "r":
            self._readers[access.domain] = self._readers.get(access.domain, 0) + 1
        else:
            self._writers.add(access.domain)

    def finish(self, access: ToolAccess) -> None:
        if not self.enabled or not access.is_stateful:
            return
        if access.access == "r":
            count = self._readers.get(access.domain, 0)
            if count <= 1:
                self._readers.pop(access.domain, None)
            else:
                self._readers[access.domain] = count - 1
        else:
            self._writers.discard(access.domain)
