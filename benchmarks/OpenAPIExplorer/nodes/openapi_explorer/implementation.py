import json
import re
import threading
from typing import Any, Dict, Optional
from urllib.parse import quote, unquote, urlparse

import requests

from atsuite_sdk.abstract import registry
from atsuite_sdk.state import register_state_object


class OpenAPIExplorer:
    """OpenAPI explorer powered by oapis.org endpoints."""

    def __init__(self, timeout_seconds: int = 45, max_chars: int = 250000) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_chars = max_chars
        self.prewarm_api_ids = ["openai", "github"]
        self.overview_cache: dict[str, str] = {}
        self.descriptor_cache: dict[str, list[dict[str, str]]] = {}
        self.descriptor_index: dict[str, dict[str, dict[str, str]]] = {}
        self.operation_cache: dict[str, dict[str, str]] = {}
        self.cache_ready = False
        self.cached_api_ids: list[str] = []
        self._warmup_lock = threading.Lock()

    def _request_text(self, url: str) -> str:
        resp = requests.get(url, timeout=self.timeout_seconds)
        resp.raise_for_status()
        text = resp.text
        if len(text) > self.max_chars:
            raise ValueError(
                f"Response too large ({len(text)} chars), max allowed {self.max_chars}."
            )
        return text

    def _fetch_overview(self, api_id: str) -> str:
        url = f"https://oapis.org/overview/{quote(api_id, safe='')}"
        return self._request_text(url)

    def _fetch_operation(self, api_id: str, operation_key: str) -> str:
        if "/" in operation_key:
            return self._fetch_operation_summary(api_id, operation_key)

        url = f"https://oapis.org/openapi/{quote(api_id, safe='')}/{operation_key}"
        try:
            return self._request_text(url)
        except ValueError as exc:
            if "Response too large" not in str(exc):
                raise
            return self._fetch_operation_summary(api_id, operation_key)

    def _fetch_operation_summary(self, api_id: str, operation_key: str) -> str:
        url = f"https://oapis.org/summary/{quote(api_id, safe='')}/{operation_key}"
        return self._request_text(url)

    def _extract_operation_descriptors(self, overview_text: str) -> list[dict[str, str]]:
        try:
            payload = json.loads(overview_text)
        except json.JSONDecodeError:
            return self._extract_operation_descriptors_from_markdown(overview_text)

        descriptors: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                operation_id = value.get("operationId") or value.get("operation_id")
                path_value = value.get("path") or value.get("route")

                normalized_operation_id = (
                    str(operation_id).strip() if isinstance(operation_id, str) and operation_id.strip() else ""
                )
                normalized_path = (
                    str(path_value).strip()
                    if isinstance(path_value, str) and str(path_value).strip().startswith("/")
                    else ""
                )
                fetch_key = normalized_operation_id or normalized_path

                if normalized_operation_id or normalized_path:
                    key = (normalized_operation_id, normalized_path, fetch_key)
                    if key not in seen:
                        seen.add(key)
                        descriptors.append(
                            {
                                "operation_id": normalized_operation_id,
                                "path": normalized_path,
                                "fetch_key": fetch_key,
                            }
                        )

                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(payload)

        if not descriptors:
            raise ValueError("No operations found in overview payload.")
        return descriptors

    def _extract_operation_descriptors_from_markdown(
        self, overview_text: str
    ) -> list[dict[str, str]]:
        descriptors: list[dict[str, str]] = []
        seen: set[str] = set()

        for label, url in re.findall(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", overview_text):
            parsed = urlparse(url)
            marker = "/openapi/"
            if marker not in parsed.path:
                continue

            suffix = parsed.path.split(marker, 1)[1]
            parts = suffix.split("/", 1)
            if len(parts) != 2:
                continue

            _, raw_operation_key = parts
            fetch_key = unquote(raw_operation_key).strip()
            operation_id = label.strip()
            if not fetch_key:
                continue
            if fetch_key in seen:
                continue

            seen.add(fetch_key)
            descriptors.append(
                {
                    "operation_id": operation_id or fetch_key,
                    "path": fetch_key if fetch_key.startswith("/") else "",
                    "fetch_key": fetch_key,
                }
            )

        if not descriptors:
            raise ValueError("Overview payload is neither valid JSON nor supported markdown.")
        return descriptors

    def _fetch_operation_with_alias_fallback(self, api_id: str, descriptor: dict[str, str]) -> tuple[str, list[str]]:
        fetch_key = descriptor.get("fetch_key", "")
        operation_id = descriptor.get("operation_id", "")
        path_value = descriptor.get("path", "")

        aliases: list[str] = []
        candidates: list[str] = []
        for value in (fetch_key, operation_id, path_value):
            if value and value not in aliases:
                aliases.append(value)
                candidates.append(value)

        if not candidates:
            raise ValueError(f"Operation descriptor for '{api_id}' has no usable identifiers.")

        last_error: Optional[Exception] = None
        for candidate in candidates:
            try:
                return self._fetch_operation(api_id, candidate), aliases
            except Exception as exc:  # pragma: no cover - exercised via fallback behavior
                last_error = exc

        assert last_error is not None
        raise last_error

    @staticmethod
    def _build_descriptor_index(
        descriptors: list[dict[str, str]]
    ) -> dict[str, dict[str, str]]:
        index: dict[str, dict[str, str]] = {}
        for descriptor in descriptors:
            for key in (
                descriptor.get("fetch_key", ""),
                descriptor.get("operation_id", ""),
                descriptor.get("path", ""),
            ):
                normalized = str(key).strip()
                if normalized and normalized not in index:
                    index[normalized] = descriptor
        return index

    def _ensure_api_cached(self, api_id: str) -> None:
        if api_id in self.overview_cache:
            return

        with self._warmup_lock:
            if api_id in self.overview_cache:
                return

            overview_text = self._fetch_overview(api_id)
            descriptors = self._extract_operation_descriptors(overview_text)
            self.overview_cache[api_id] = overview_text
            self.descriptor_cache[api_id] = descriptors
            self.descriptor_index[api_id] = self._build_descriptor_index(descriptors)
            self.operation_cache.setdefault(api_id, {})
            if api_id not in self.cached_api_ids:
                self.cached_api_ids.append(api_id)

    def warmup_all_specs(self) -> None:
        for api_id in self.prewarm_api_ids:
            self._ensure_api_cached(api_id)
        self.cache_ready = True

    def ensure_warm(self) -> None:
        if self.cache_ready:
            return
        self.warmup_all_specs()

    @staticmethod
    def _to_json_string(data: Dict[str, Any]) -> str:
        return json.dumps(data, ensure_ascii=False)

    def get_api_overview(self, api_id: str) -> str:
        api_id = str(api_id).strip()
        if not api_id:
            return self._to_json_string(
                {"isError": True, "error": "api_id cannot be empty"}
            )

        try:
            self._ensure_api_cached(api_id)
            cached = self.overview_cache.get(api_id)
            if cached is None:
                raise KeyError(f"Overview for api_id '{api_id}' not found in cache.")
            return cached
        except Exception as exc:
            return self._to_json_string(
                {"isError": True, "error": str(exc), "api_id": api_id}
            )

    def get_api_operation(
        self,
        api_id: str,
        operation_id_or_route: Optional[str] = None,
        operationIdOrRoute: Optional[str] = None,
    ) -> str:
        api_id = str(api_id).strip()
        op = operation_id_or_route or operationIdOrRoute
        op = str(op).strip() if op is not None else ""

        if not api_id:
            return self._to_json_string(
                {"isError": True, "error": "api_id cannot be empty"}
            )
        if not op:
            return self._to_json_string(
                {
                    "isError": True,
                    "error": "operation_id_or_route (or operationIdOrRoute) cannot be empty",
                    "api_id": api_id,
                }
            )

        try:
            self._ensure_api_cached(api_id)
            per_api_cache = self.operation_cache.get(api_id, {})
            cached = per_api_cache.get(op)
            if cached is None:
                descriptor = self.descriptor_index.get(api_id, {}).get(op)
                if descriptor is not None:
                    operation_text, aliases = self._fetch_operation_with_alias_fallback(
                        api_id, descriptor
                    )
                    for alias in aliases:
                        per_api_cache[alias] = operation_text
                    cached = operation_text
                else:
                    operation_text = self._fetch_operation(api_id, op)
                    per_api_cache[op] = operation_text
                    cached = operation_text
            return cached
        except Exception as exc:
            return self._to_json_string(
                {
                    "isError": True,
                    "error": str(exc),
                    "api_id": api_id,
                    "operation": op,
                }
            )


openapi_explorer = OpenAPIExplorer()
register_state_object("openapi_explorer", openapi_explorer)


@registry.tool(stateful=True)
def openapi_explorer_get_api_overview(id: str) -> str:
    """Get overview of an OpenAPI specification by id."""
    return openapi_explorer.get_api_overview(id)


@registry.tool(stateful=True)
def openapi_explorer_get_api_operation(
    id: str,
    operation_id_or_route: Optional[str] = None,
    operationIdOrRoute: Optional[str] = None,
) -> str:
    """Get details for a specific OpenAPI operation (operation id or route)."""
    return openapi_explorer.get_api_operation(
        id,
        operation_id_or_route=operation_id_or_route,
        operationIdOrRoute=operationIdOrRoute,
    )
