from __future__ import annotations

import base64
import contextvars
import json
import os
import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Optional

_SKIP = object()
_CURRENT_UID = contextvars.ContextVar("atsuite_current_uid", default="default")
_SYNC_TIMING = contextvars.ContextVar("atsuite_state_sync_timing", default=None)


def _safe_uid(uid: Optional[str]) -> str:
    raw = str(uid or "default")
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in raw)
    return cleaned or "default"


class StateRuntime:
    """State runtime for MCP/FaaS stateful tools.

    - MCP mode: per-session state stored in-process memory (snapshot map).
    - Function mode: per-session state restored/persisted from object storage.
    """

    def __init__(self) -> None:
        self.runtime = os.getenv("ATSUITE_RUNTIME", "").strip().lower() or "function"
        self.provider = os.getenv("PROVIDER", "").strip().lower()
        self.bucket = os.getenv("PROJECT", "atsuite")
        self.service_name = (
            os.getenv("ATSUITE_STATE_SERVICE", "").strip()
            or os.getenv("ATSUITE_MCP_NAME", "").strip()
            or "atsuite-service"
        )
        self.root = Path(os.getenv("ATSUITE_SESSION_ROOT", "/tmp/atsuite_state"))
        self.root.mkdir(parents=True, exist_ok=True)

        self._registry: Dict[str, Dict[str, object]] = {}
        self._defaults: Dict[str, Dict[str, Any]] = {}
        self._memory_snapshots: Dict[str, Dict[str, Any]] = {}
        self._storage = None

        if self.runtime == "function" and (
            self.provider.startswith("ali")
           
            or self.provider.startswith("aws")
            or self.provider.startswith("gcp")
        ):
            try:
                from atsuite_sdk.storage import create_storage

                kwargs = {"provider": self.provider, "bucket": self.bucket}
                self._storage = create_storage(**kwargs)
            except Exception as e:
                print(f"[state] storage init disabled: {e}")
                self._storage = None

    def register_object(self, name: str, obj: object, module_name: Optional[str] = None) -> None:
        if module_name is None:
            module_name = self.service_name
        module = module_name
        mod_entry = self._registry.setdefault(module, {})
        mod_entry[name] = obj

        defaults = self._defaults.setdefault(module, {})
        defaults[name] = self._extract_object_state(obj)

    def list_registered(self, module_name: str) -> Dict[str, object]:
        return self._registry.get(module_name, {})

    def _resolve_uid(self, uid: Optional[str]) -> str:
        if uid is None:
            return _safe_uid(_CURRENT_UID.get())
        return _safe_uid(uid)

    @contextmanager
    def uid_context(self, uid: Optional[str]):
        token = _CURRENT_UID.set(self._resolve_uid(uid))
        try:
            yield
        finally:
            _CURRENT_UID.reset(token)

    def session_dir(self, uid: Optional[str] = None) -> Path:
        return self.root / self.service_name / self._resolve_uid(uid)

    def session_path(self, relpath: str, uid: Optional[str] = None) -> Path:
        rel = Path(relpath)
        if rel.is_absolute():
            raise ValueError("session path must be relative")

        base = self.session_dir(uid)
        path = (base / rel).resolve()
        base_resolved = base.resolve()
        if not str(path).startswith(str(base_resolved)):
            raise ValueError("session path escapes session directory")
        return path

    def session_open(self, relpath: str, mode: str = "r", *args, uid: Optional[str] = None, **kwargs):
        path = self.session_path(relpath, uid=uid)
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            path.parent.mkdir(parents=True, exist_ok=True)
        return path.open(mode, *args, **kwargs)

    def reset_sync_metrics(self) -> None:
        _SYNC_TIMING.set({"load_ms": 0.0, "save_ms": 0.0})

    def get_sync_metrics(self) -> Dict[str, float]:
        raw = _SYNC_TIMING.get()
        if not isinstance(raw, dict):
            raw = {"load_ms": 0.0, "save_ms": 0.0}
        load_ms = self._coerce_metric_ms(raw.get("load_ms"))
        save_ms = self._coerce_metric_ms(raw.get("save_ms"))
        return {
            "load_ms": round(load_ms, 3),
            "save_ms": round(save_ms, 3),
            "total_ms": round(load_ms + save_ms, 3),
        }

    @staticmethod
    def _coerce_metric_ms(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _should_measure_sync_overhead(self) -> bool:
        return self.runtime != "mcp" and self._storage is not None

    def _record_sync_timing(self, key: str, start_ns: int) -> None:
        raw = _SYNC_TIMING.get()
        if not isinstance(raw, dict):
            raw = {"load_ms": 0.0, "save_ms": 0.0}
        raw[key] = self._coerce_metric_ms(raw.get(key)) + (
            (time.perf_counter_ns() - start_ns) / 1_000_000
        )
        _SYNC_TIMING.set(raw)

    def load_for_tool(self, tool_module: str, uid: Optional[str]) -> None:
        if not self._registry:
            return
        sync_start_ns = time.perf_counter_ns() if self._should_measure_sync_overhead() else 0
        try:
            snap = self._get_snapshot(uid)
            self._restore_files(uid, snap.get("files") or {})

            all_vars = snap.get("vars") or {}
            for module, named in self._registry.items():
                module_vars = all_vars.get(module) or {}
                module_defaults = self._defaults.get(module, {})
                for name, obj in named.items():
                    target_vars = module_vars.get(name)
                    if target_vars is None:
                        for other_module, other_vars in all_vars.items():
                            if other_module != module and isinstance(other_vars, dict):
                                candidate = other_vars.get(name)
                                if candidate is not None:
                                    target_vars = candidate
                                    break
                    if target_vars is None:
                        target_vars = module_defaults.get(name, {})
                    self._apply_object_state(obj, target_vars)
        finally:
            if sync_start_ns:
                self._record_sync_timing("load_ms", sync_start_ns)

    def save_after_tool(self, tool_module: str, uid: Optional[str]) -> None:
        if not self._registry:
            return
        sync_start_ns = time.perf_counter_ns() if self._should_measure_sync_overhead() else 0
        try:
            vars_by_module: Dict[str, Dict[str, Any]] = {}
            for module, named in self._registry.items():
                vars_by_module[module] = {
                    name: self._extract_object_state(obj) for name, obj in named.items()
                }

            snap = {
                "version": 1,
                "vars": vars_by_module,
                "files": self._capture_files(uid),
            }
            self._set_snapshot(uid, snap)
        finally:
            if sync_start_ns:
                self._record_sync_timing("save_ms", sync_start_ns)

    def _snapshot_key(self, uid: Optional[str]) -> str:
        return f"{self.service_name}/{_safe_uid(uid)}.json"

    def _get_snapshot(self, uid: Optional[str]) -> Dict[str, Any]:
        if self.runtime == "mcp":
            return self._memory_snapshots.get(_safe_uid(uid), {})

        if self._storage is None:
            return {}

        key = self._snapshot_key(uid)
        content = self._storage.read(key)
        if not content:
            return {}
        try:
            payload = json.loads(content)
            return payload if isinstance(payload, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _set_snapshot(self, uid: Optional[str], snapshot: Dict[str, Any]) -> None:
        if self.runtime == "mcp":
            self._memory_snapshots[_safe_uid(uid)] = snapshot
            return

        if self._storage is None:
            return
        key = self._snapshot_key(uid)
        blob = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
        self._storage.clearobj(key)
        self._storage.append(key, blob)

    def prime_snapshot(self, uid: Optional[str], snapshot: Dict[str, Any]) -> None:
        if not isinstance(snapshot, dict):
            return
        self._set_snapshot(uid, snapshot)

    def _capture_files(self, uid: Optional[str]) -> Dict[str, str]:
        base = self.session_dir(uid)
        if not base.exists():
            return {}
        files: Dict[str, str] = {}
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(base).as_posix()
            files[rel] = base64.b64encode(path.read_bytes()).decode("ascii")
        return files

    def _restore_files(self, uid: Optional[str], files: Dict[str, str]) -> None:
        base = self.session_dir(uid)
        if base.exists():
            shutil.rmtree(base)
        base.mkdir(parents=True, exist_ok=True)

        for rel, encoded in files.items():
            path = self.session_path(rel, uid=uid)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(encoded.encode("ascii")))

    def _extract_object_state(self, obj: object) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        for key, value in vars(obj).items():
            if key.startswith("_"):
                continue
            if callable(value):
                continue
            encoded = self._to_json_compatible(value)
            if encoded is _SKIP:
                continue
            data[key] = encoded
        return data

    def _apply_object_state(self, obj: object, data: Dict[str, Any]) -> None:
        for key, value in data.items():
            setattr(obj, key, value)

    def _to_json_compatible(self, value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, list):
            out = []
            for item in value:
                converted = self._to_json_compatible(item)
                if converted is _SKIP:
                    return _SKIP
                out.append(converted)
            return out
        if isinstance(value, tuple):
            out = []
            for item in value:
                converted = self._to_json_compatible(item)
                if converted is _SKIP:
                    return _SKIP
                out.append(converted)
            return out
        if isinstance(value, dict):
            out: Dict[str, Any] = {}
            for k, v in value.items():
                if not isinstance(k, str):
                    return _SKIP
                converted = self._to_json_compatible(v)
                if converted is _SKIP:
                    return _SKIP
                out[k] = converted
            return out
        return _SKIP


_RUNTIME = StateRuntime()


def get_state_runtime() -> StateRuntime:
    return _RUNTIME


def register_state_object(name: str, obj: object, module_name: Optional[str] = None) -> None:
    if module_name is None:
        import inspect
        caller_frame = inspect.currentframe()
        if caller_frame and caller_frame.f_back:
            caller_module = caller_frame.f_back.f_globals.get("__name__")
            if caller_module:
                module_name = caller_module
    _RUNTIME.register_object(name, obj, module_name=module_name)


def session_path(relpath: str, uid: Optional[str] = None) -> str:
    return str(_RUNTIME.session_path(relpath, uid=uid))


def session_open(relpath: str, mode: str = "r", *args, uid: Optional[str] = None, **kwargs):
    return _RUNTIME.session_open(relpath, mode, *args, uid=uid, **kwargs)
