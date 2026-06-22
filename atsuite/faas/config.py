from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from atsuite.utils import load_json


@dataclass(frozen=True)
class FunctionRuntimeConfig:
    cpu: int = 1
    memory: int = 1
    timeout: int = 1
    disk: int = 1


def function_config_path(node_dir: Path) -> Path:
    return node_dir / "function-config.json"


def _read_first_function(config: Dict[str, Any]) -> Dict[str, Any]:
    functions = config.get("functions") or []
    if isinstance(functions, list) and functions:
        return functions[0] if isinstance(functions[0], dict) else {}
    return {}


def load_function_config(path: Path) -> FunctionRuntimeConfig:
    config = load_json(path)
    first = _read_first_function(config)
    return FunctionRuntimeConfig(
        cpu=int(first.get("cpu", 1)),
        memory=int(first.get("memory", 1)),
        timeout=int(first.get("timeout", 1)),
        disk=int(first.get("disk", 1)),
    )
