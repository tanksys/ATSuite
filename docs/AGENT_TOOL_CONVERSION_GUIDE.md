# Tool Conversion Guide

This guide explains how to convert original tool implementations to be compatible with ATSuite. When provided with this guide and original tool code, you can generate complete ATSuite-compatible node directories with all required files.

## Original Code Structure

Original tool implementations typically follow this pattern:

```python
# Original imports
import pandas as pd
from pandas import DataFrame
from typing import Optional
from utils.func import extract_before_parenthesis

class ToolClassName:
    def __init__(self, path="../database/tool_name/data.csv"):
        self.path = path
        self.data = pd.read_csv(self.path).dropna()[[...]]
        print("Tool loaded.")

    def run(self, param1: str, param2: str, ...) -> DataFrame:
        """Original method implementation"""
        # ... logic here
        return results
    
    def run_for_annotation(self, param1: str, param2: str, ...) -> DataFrame:
        """Annotation-specific method"""
        # ... logic here
        return results
        
    # Additional methods may exist (e.g., get_city_set, load_db, etc.)
```

## Complete Node Directory Structure

Each converted tool should be placed in its own directory with the following files:

```
{tool_name}/
├── implementation.py          # Main implementation file
├── function-config.json       # FaaS deployment configuration  
├── mcp-config.json            # MCP server deployment configuration
├── requirements.txt           # Python dependencies
└── init.sh                    # Data initialization script (optional)
```

## File Templates

### 1. implementation.py

There are two types of tools: **stateless** and **stateful**.

#### Stateless Tools (Read-only, no persistent state)

```python
import pandas as pd
from pandas import DataFrame
from typing import Optional
import re
from atsuite_sdk.abstract import registry

# =============================
# Original Implementation  
# [Include link to original source if available]
# =============================

def extract_before_parenthesis(s):
    match = re.search(r'^(.*?)\([^)]*\)', s)
    return match.group(1) if match else s

class {ToolClassName}:
    def __init__(self, path="./{data_filename}.csv"):
        self.path = path
        self.data = pd.read_csv(self.path).dropna()[[...]]
        print("{ToolName} loaded.")

    def run(self, {parameters}) -> DataFrame:
        """Original method implementation"""
        # ... logic here
        return results
    
    def run_for_annotation(self, {parameters}) -> DataFrame:
        """Annotation-specific method"""
        # ... logic here  
        return results

# =============================
# Definitions for Agent Tools
# =============================

{tool_instance_name} = {ToolClassName}()
    
@registry.tool()
def {tool_name}_run_for_annotation({parameters}) -> DataFrame:
    """Search functionality for annotation."""
    return {tool_instance_name}.run_for_annotation({parameters})

@registry.tool()
def {tool_name}_run({parameters}) -> DataFrame:
    """Main search functionality."""  
    return {tool_instance_name}.run({parameters})
```

#### Stateful Tools (Maintain persistent state across calls)

```python
import json
from io import StringIO
import pandas as pd
from pandas import DataFrame
from atsuite_sdk.abstract import registry
from atsuite_sdk.storage import create_storage

# =============================
# Original Implementation  
# [Include link to original source if available]
# =============================

class {ToolClassName}:
    def __init__(self, storage) -> None:
        self.storage = storage

    def _key(self, uid: str) -> str:
        return f"{tool_name}/{uid}.json"

    def _load_all(self, uid: str) -> list[dict]:
        content = self.storage.read(self._key(uid))
        if not content:
            return []
        lines = [l for l in content.splitlines() if l.strip()]
        return [json.loads(l) for l in lines]

    # Convert original methods to include uid parameter and use storage
    def original_method_name(self, {original_parameters}, uid: str):
        """Converted method with state support"""
        # Load existing data if needed
        # data = self._load_all(uid)
        
        # Perform operation using self.storage
        # Save results using self.storage.append() or self.storage.clearobj()
        
        return result

# =============================
# Definitions for Agent Tools
# =============================

# For DataFrame parameters, convert to string input and parse with pd.read_json
@registry.tool(stateful=True, uid_param="uid", storage_class=lambda: create_storage("oss", bucket="atsuite"))
def {tool_name}_method_name({converted_parameters}, uid: str, _storage=None, _uid=None):
    # Convert string inputs back to DataFrame if needed
    # df = pd.read_json(StringIO(input_data), orient="records")
    
    tool_instance = {ToolClassName}(_storage)
    return tool_instance.original_method_name({original_parameters}, _uid)

# Repeat for each method that needs to be exposed
# Function names should follow the pattern: {tool_name}_{method_name}
```

### 2. function-config.json

```json
{
    "name": "{tool_name}",
    "python-version": "3.10",
    "functions": [
    {
        "name": "{tool_name}.run",
        "cpu": 1,
        "memory": 1024,
        "disk": 512,
        "timeout": 30
    },
    {
        "name": "{tool_name}.run_for_annotation", 
        "cpu": 1,
        "memory": 1024,
        "disk": 512,
        "timeout": 30
    }
    ]
}
```

**说明：**
- `cpu`: CPU 核心数（默认 1）
- `memory`: 内存大小（MB，默认 1024）
- `disk`: 磁盘空间（MB，默认 512）
- `timeout`: 超时时间（秒，默认 30）


### 3. mcp-config.json

```json
{
    "name": "{tool_name}",
    "description": "{ToolName} MCP Server",
    "python-version": "3.10",
    "cpu": 1,
    "memory": 1024,
    "timeout": 30
}
```

### 4. requirements.txt

List all Python dependencies (typically just `pandas` for TravelPlanner tools):

```
pandas
```

### 5. init.sh (Optional)

用于在构建 Docker 镜像时复制数据文件到镜像中。

```bash
#! /bin/bash

OUTPUT_DIR="${1:-.}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOME_DIR="$(dirname "$(dirname "$(dirname "$(dirname "$(dirname "${SCRIPT_DIR}")")")")")"
SRC_PATH="${ATSUITE_DATA_PATH:-${HOME_DIR}/atsuite_data/{benchmark_name}/{tool_name}/{data_filename}.csv}"
DST_PATH="${OUTPUT_DIR}/{data_filename}.csv"

if [ ! -f "${SRC_PATH}" ]; then
  echo "Dataset not found at ${SRC_PATH}"
  exit 1
fi

cp "${SRC_PATH}" "${DST_PATH}"
```

**说明：**
- `SCRIPT_DIR`：获取 `init.sh` 所在目录
- `HOME_DIR`：向上 5 层目录，从 `dist/{benchmark}/{tool}/` 到 `/home/{user}/`
- `ATSUITE_DATA_PATH`：可通过环境变量覆盖数据路径
- `{benchmark_name}`：基准测试名称（如 `travelplanner`）
- `{tool_name}`：工具名称（如 `flights`, `restaurants`, `accommodations`）
- `{data_filename}`：数据文件名（如 `clean_Flights_2022.csv`）

**示例：**
- `flights/init.sh` → `.../atsuite_data/travelplanner/flights/clean_Flights_2022.csv`
- `restaurants/init.sh` → `.../atsuite_data/travelplanner/restaurants/clean_restaurant_2022.csv`

## Conversion Requirements

### Determining Tool Type
- **Stateless**: Tools that only read data and return results without modifying internal state (e.g., search, query functions)
- **Stateful**: Tools that maintain or modify persistent state across multiple calls (e.g., notebook, task manager, shopping cart)

### Path and Import Changes
- Replace `from utils.func import extract_before_parenthesis` with direct regex implementation
- Add `from atsuite_sdk.abstract import registry` for tool registration
- For stateful tools, also import `from atsuite_sdk.storage import create_storage`
- Change database paths from relative (`../database/...`) to local (`./filename.csv`)

### Tool Registration
- **Stateless**: Use `@registry.tool()` decorator
- **Stateful**: Use `@registry.tool(stateful=True, uid_param="uid", storage_class=lambda: create_storage("oss", bucket="atsuite"))`
- Function names should match the original class methods exactly
- For stateful tools, add `uid: str` parameter and `_storage=None, _uid=None` parameters to wrapper functions

### Configuration Files
- **function-config.json**: Define each registered function as a separate FaaS function
- **mcp-config.json**: Single MCP server configuration for the entire tool
- **requirements.txt**: Include all necessary dependencies (usually `pandas`)
- **init.sh**: Create data initialization script if original data path is known

## Generation Instructions

When given original tool code and a target directory path `{target_path}/{tool_name}`, generate:

1. **Directory**: Create `{target_path}/{tool_name}/` directory
2. **implementation.py**: Apply appropriate conversion template based on whether the tool is stateless or stateful
3. **function-config.json**: Configure FaaS functions based on registered methods
4. **mcp-config.json**: Configure MCP server with tool name and description
5. **requirements.txt**: Add required dependencies
6. **init.sh**: Create data initialization script if original data path is known

## Example Usage

**Input**: Original Accommodations class (stateless) + target path `/output/accommodations`
**Output**: Complete directory structure with stateless implementation

**Input**: Original TaskManager class (stateful) + target path `/output/task_manager`  
**Output**: Complete directory structure with stateful implementation using storage

This approach ensures tools can be deployed across different cloud providers (Local, Alibaba Cloud, AWS Lambda) while maintaining compatibility with the original functionality.
