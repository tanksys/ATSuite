# 工具转换指南

本文说明如何把原始工具实现转换为 ATSuite 兼容的 node 目录。给定原始工具代码后，可以按这里的结构生成完整的 node 文件。

## 原始工具结构

原始工具通常类似下面形式：

```python
import pandas as pd
from pandas import DataFrame
from typing import Optional

class ToolClassName:
    def __init__(self, path="../database/tool_name/data.csv"):
        self.path = path
        self.data = pd.read_csv(self.path).dropna()[...]

    def run(self, param1: str, param2: str, ...) -> DataFrame:
        return results

    def run_for_annotation(self, param1: str, param2: str, ...) -> DataFrame:
        return results
```

## Node 目录结构

每个工具应放在独立目录下：

```text
{tool_name}/
├── implementation.py
├── function-config.json
├── mcp-config.json
├── requirements.txt
└── init.sh
```

## `implementation.py`

工具通过 `atsuite_sdk.abstract.registry` 暴露给 ATSuite。

### 无状态工具

无状态工具只读数据，不需要跨调用持久化：

```python
import pandas as pd
from atsuite_sdk.abstract import registry

class ToolClassName:
    def __init__(self, path="./data.csv"):
        self.data = pd.read_csv(path)

    def run(self, query: str):
        return self.data

tool = ToolClassName()

@registry.tool()
def tool_run(query: str):
    """Main tool entrypoint."""
    return tool.run(query)
```

### 有状态工具

有状态工具需要显式接收 `uid`，并通过存储后端保存每个用户的状态：

```python
import json
from atsuite_sdk.abstract import registry
from atsuite_sdk.storage import create_storage

class ToolClassName:
    def __init__(self, storage):
        self.storage = storage

    def _key(self, uid: str) -> str:
        return f"tool/{uid}.json"

    def write(self, value: str, uid: str):
        self.storage.append(self._key(uid), json.dumps({"value": value}) + "\n")
        return "ok"

@registry.tool(stateful=True, uid_param="uid", storage_class=lambda: create_storage("oss", bucket="atsuite"))
def tool_write(value: str, uid: str, _storage=None, _uid=None):
    tool = ToolClassName(_storage)
    return tool.write(value, _uid)
```

## `function-config.json`

```json
{
  "name": "tool_name",
  "python-version": "3.10",
  "functions": [
    {
      "name": "tool_name.run",
      "cpu": 1,
      "memory": 1024,
      "disk": 512,
      "timeout": 30
    }
  ]
}
```

字段含义：

- `cpu`：CPU 核数。
- `memory`：内存大小，单位 MB。
- `disk`：临时磁盘大小，单位 MB。
- `timeout`：超时时间，单位秒。

## `mcp-config.json`

```json
{
  "name": "tool_name",
  "description": "Tool MCP Server",
  "python-version": "3.10",
  "cpu": 1,
  "memory": 1024,
  "timeout": 30
}
```

## `requirements.txt`

列出工具运行需要的 Python 依赖。例如：

```text
pandas
```

## `init.sh`

`init.sh` 用于在构建 Docker 镜像时复制数据文件：

```bash
#! /bin/bash

OUTPUT_DIR="${1:-.}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_PATH="${ATSUITE_DATA_PATH:-${SCRIPT_DIR}/data.csv}"
DST_PATH="${OUTPUT_DIR}/data.csv"

if [ ! -f "${SRC_PATH}" ]; then
  echo "Dataset not found at ${SRC_PATH}"
  exit 1
fi

cp "${SRC_PATH}" "${DST_PATH}"
```
