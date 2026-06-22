from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from atsuite.utils import load_json


@dataclass(frozen=True)
class MCPRuntimeConfig:
    cpu: int = 1
    memory: int = 1024
    timeout: int = 30
    data: dict = None

    def __post_init__(self):
        if self.data is None:
            object.__setattr__(self, "data", {})


def mcp_config_path(node_dir: Path) -> Path:
    return node_dir / "mcp-config.json"


def load_mcp_config(path: Path) -> MCPRuntimeConfig:
    if not path.exists():
        return MCPRuntimeConfig()
    data = load_json(path)
    return MCPRuntimeConfig(
        cpu=int(data.get("cpu", 1)),
        memory=int(data.get("memory", 1024)),
        timeout=int(data.get("timeout", 30)),
        data=data,
    )
