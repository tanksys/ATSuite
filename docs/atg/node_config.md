# Node Configuration

Benchmark configuration is composed of three parts:

- trace file reference
- tool binding
- runtime pipeline

Legacy `sandbox` nodes are not supported by the current runtime path. If a benchmark needs sandbox lifecycle behavior, expose it through an external MCP-Gateway or router as a `tool_use` endpoint.

## Tool Binding

The legacy binding format is still accepted:

```json
{
  "name": "notebook",
  "dir": "./nodes/notebook",
  "trace_names": [
    {
      "name": "notebook.write",
      "tool": "notebook_write",
      "domain": "notebook",
      "access": "rw"
    },
    {
      "name": "notebook.list_all",
      "tool": "notebook_list_all",
      "access": "stateless"
    }
  ]
}
```

`access` can be one of:

- `stateless`
- `r`
- `w`
- `rw`

The legacy field `stateful: true` is mapped to `access=rw`. If `domain` is omitted, it defaults to the node name.

## Pipeline

FaaS targets use `pipeline.faas.units`:

```json
{
  "name": "notebook",
  "node": "notebook",
  "trace_names": ["notebook.write"],
  "deploy": {
    "cpu": 1,
    "memory": 1024,
    "disk": 512,
    "timeout": 30
  }
}
```

Session-MCP targets use `pipeline.session.servers`. The older name `pipeline.mcp_serverless.servers` is still accepted:

```json
{
  "name": "travelplanner_notebook",
  "nodes": ["notebook"],
  "deploy": {
    "cpu": 2,
    "memory": 2048,
    "disk": 512,
    "timeout": 30
  }
}
```

During build, ATSuite chooses either a FaaS function image or an MCP server image based on the selected provider and target family.
