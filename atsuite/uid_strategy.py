from __future__ import annotations

from typing import Optional


def build_request_uid(
    *,
    uid_prefix: str,
    index: int,
    uid_mode: str,
    uid_fixed: Optional[str],
    uuid_hex: str,
) -> str:
    mode = str(uid_mode).strip().lower()
    if mode == "index":
        return f"{uid_prefix}_{index}"
    if mode == "fixed":
        if not uid_fixed:
            raise ValueError("uid_fixed is required when uid_mode=fixed")
        return uid_fixed
    if mode == "random":
        return f"{uid_prefix}_{index}_{uuid_hex[:8]}"
    raise ValueError(f"unsupported uid mode: {uid_mode}")
