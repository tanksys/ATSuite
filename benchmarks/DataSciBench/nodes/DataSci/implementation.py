import importlib
import io
import os
import shutil
import traceback
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

from atsuite_sdk.abstract import registry
from atsuite_sdk.state import get_state_runtime, register_state_object

_NODE_DIR = Path(__file__).resolve().parent
_SESSION_PARENT_SEED_FILES = (
    ("bootstrap/data_pums_2000.csv", "data_pums_2000.csv"),
    ("bootstrap/adult.data", "adult.data"),
    ("bootstrap/adult.test", "adult.test"),
)
_STATE_TYPE_KEY = "__atsuite_state_type__"
_DATAFRAME_STATE = "dataframe"
_SERIES_STATE = "series"


class DataSciWorkspace:
    def __init__(self) -> None:
        self.variables: dict[str, Any] = {}
        self.imported_modules: dict[str, str] = {}

    def namespace(self) -> dict[str, Any]:
        ns: dict[str, Any] = {"__builtins__": __builtins__}
        for alias, module_name in self.imported_modules.items():
            ns[alias] = importlib.import_module(module_name)
        for name, value in self.variables.items():
            ns[name] = _from_state_value(value)
        return ns

    def sync_from_namespace(self, ns: dict[str, Any]) -> None:
        saved_variables: dict[str, Any] = {}
        imported_modules: dict[str, str] = {}

        for name, value in ns.items():
            if name.startswith("__"):
                continue
            if isinstance(value, ModuleType):
                imported_modules[name] = value.__name__
                continue
            if callable(value):
                continue

            try:
                converted = _to_state_value(value)
            except TypeError:
                continue
            else:
                saved_variables[name] = converted

        self.variables = saved_variables
        self.imported_modules = imported_modules

    def reset(self) -> None:
        self.variables = {}
        self.imported_modules = {}

    def names(self) -> list[str]:
        return sorted(set(self.imported_modules.keys()) | set(self.variables.keys()))


datasci_workspace = DataSciWorkspace()
register_state_object("datasci_workspace", datasci_workspace)


def _to_state_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    dataframe_state = _maybe_dataframe_state(value)
    if dataframe_state is not None:
        return dataframe_state
    series_state = _maybe_series_state(value)
    if series_state is not None:
        return series_state
    if hasattr(value, "tolist"):
        try:
            return _to_state_value(value.tolist())
        except Exception:
            raise TypeError("unsupported state value") from None
    if hasattr(value, "item"):
        try:
            return _to_state_value(value.item())
        except Exception:
            raise TypeError("unsupported state value") from None
    if isinstance(value, dict):
        converted_dict: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("unsupported state value")
            converted_item = _to_state_value(item)
            converted_dict[key] = converted_item
        return converted_dict
    if isinstance(value, (list, tuple)):
        converted_list = []
        for item in value:
            converted_list.append(_to_state_value(item))
        return converted_list
    raise TypeError("unsupported state value")


def _maybe_dataframe_state(value: Any) -> Optional[dict[str, Any]]:
    if not _is_dataframe_like(value):
        return None
    payload = value.to_dict(orient="split")
    if not isinstance(payload, dict):
        raise TypeError("unsupported dataframe state")
    return {
        _STATE_TYPE_KEY: _DATAFRAME_STATE,
        "value": {
            "index": _to_state_value(payload.get("index", [])),
            "columns": _to_state_value(payload.get("columns", [])),
            "data": _to_state_value(payload.get("data", [])),
        },
    }


def _maybe_series_state(value: Any) -> Optional[dict[str, Any]]:
    if not _is_series_like(value):
        return None
    return {
        _STATE_TYPE_KEY: _SERIES_STATE,
        "value": {
            "data": _to_state_value(value.tolist()),
            "name": _to_state_value(getattr(value, "name", None)),
            "index": _to_state_value(list(getattr(value, "index", []))),
        },
    }


def _from_state_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_from_state_value(item) for item in value]
    if not isinstance(value, dict):
        return value

    state_type = value.get(_STATE_TYPE_KEY)
    if state_type == _DATAFRAME_STATE:
        pandas = importlib.import_module("pandas")
        payload = value["value"]
        return pandas.DataFrame(
            _from_state_value(payload["data"]),
            columns=_from_state_value(payload["columns"]),
            index=_from_state_value(payload["index"]),
        )
    if state_type == _SERIES_STATE:
        pandas = importlib.import_module("pandas")
        payload = value["value"]
        return pandas.Series(
            _from_state_value(payload["data"]),
            name=_from_state_value(payload["name"]),
            index=_from_state_value(payload["index"]),
        )

    return {key: _from_state_value(item) for key, item in value.items()}


def _is_dataframe_like(value: Any) -> bool:
    try:
        pandas = importlib.import_module("pandas")
    except Exception:
        pandas = None

    if pandas is not None:
        dataframe_type = getattr(pandas, "DataFrame", None)
        if dataframe_type is not None and isinstance(value, dataframe_type):
            return True

    return value.__class__.__name__ == "DataFrame" and hasattr(value, "to_dict")


def _is_series_like(value: Any) -> bool:
    try:
        pandas = importlib.import_module("pandas")
    except Exception:
        pandas = None

    if pandas is not None:
        series_type = getattr(pandas, "Series", None)
        if series_type is not None and isinstance(value, series_type):
            return True

    return value.__class__.__name__ == "Series" and hasattr(value, "tolist")


def _ensure_workspace(uid: Optional[str]) -> Path:
    runtime = get_state_runtime()
    workspace = runtime.session_dir(uid)
    workspace.mkdir(parents=True, exist_ok=True)

    for src_rel, dst_name in _SESSION_PARENT_SEED_FILES:
        src = _NODE_DIR / src_rel
        dst = workspace.parent / dst_name
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)

    return workspace


@contextmanager
def _workspace_cwd(uid: Optional[str]):
    workspace = _ensure_workspace(uid)
    prev_cwd = Path.cwd()
    os.chdir(workspace)
    try:
        yield workspace
    finally:
        os.chdir(prev_cwd)


def run_code(code_str: str, uid: Optional[str] = None) -> str:
    output_buffer = io.StringIO()
    try:
        with (
            _workspace_cwd(uid) as workspace,
            redirect_stdout(output_buffer),
            redirect_stderr(output_buffer),
        ):
            ns = datasci_workspace.namespace()
            ns["__file__"] = str(workspace / "__session__.py")
            exec(code_str.strip(), ns)
            datasci_workspace.sync_from_namespace(ns)
    except Exception:
        return f"{output_buffer.getvalue()}{traceback.format_exc()}"

    return output_buffer.getvalue()


@registry.tool(stateful=True)
def datasci_run_code(code_str: str, uid: Optional[str] = None) -> str:
    return run_code(code_str, uid)


__all__ = [
    "datasci_run_code",
    "datasci_workspace",
]
