## 构建配置约定

Benchmark 配置由 trace、tool binding 和 pipeline 三部分组成。`sandbox` 节点已不再支持；需要沙箱生命周期时，应通过外部 MCP-Gateway/router 暴露 MCP endpoint。

### Tool binding

旧格式仍可使用：

```json
{
  "name": "notebook",
  "dir": "./nodes/notebook",
  "trace_names": [
    { "name": "notebook.write", "tool": "notebook_write", "domain": "notebook", "access": "rw" },
    { "name": "notebook.list_all", "tool": "notebook_list_all", "access": "stateless" }
  ]
}
```

`access` 取值为 `stateless`、`r`、`w` 或 `rw`。旧字段 `stateful: true` 会自动映射为 `access=rw`，`domain` 默认为 node name。

### Pipeline

FaaS 目标使用 `pipeline.faas.units`：

```json
{
  "name": "notebook",
  "node": "notebook",
  "trace_names": ["notebook.write"],
  "deploy": { "cpu": 1, "memory": 1024, "disk": 512, "timeout": 30 }
}
```

Session-MCP 目标使用 `pipeline.session.servers`，兼容旧名 `pipeline.mcp_serverless.servers`：

```json
{
  "name": "travelplanner_notebook",
  "nodes": ["notebook"],
  "deploy": { "cpu": 2, "memory": 2048, "disk": 512, "timeout": 30 }
}
```

Build 阶段会根据 provider 和 target family 选择 FaaS function image 或 MCP server image。
