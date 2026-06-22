# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

ATSuite is a framework for benchmarking AI Agent infrastructure performance across cloud providers. It decouples LLM inference from infrastructure execution to measure latency, cold start, cost, and memory usage.

## Development Commands

All commands use `uv` (Astral's Python package manager):

```bash
# Install dependencies (with Alibaba Cloud support)
uv sync --group aliyun

# Build Docker images for a benchmark
uv run python -m tools.build_docker_images \
    --config benchmarks/TravelPlanner/config/faas7_mcp2_min.json \
    --provider aws_lambda

# Deploy nodes to a provider
uv run python -m tools.deploy \
    --config benchmarks/TravelPlanner/config/faas7_mcp2_min.json \
    --provider aws_lambda

# Run/invoke a benchmark
uv run python -m tools.invoker \
    --config benchmarks/TravelPlanner/config/faas7_mcp2_min.json \
    --url-map url_results/faas7_mcp2_min.json \
    --provider aws_lambda \
    --uid demo

# Run trace viewer server
uv run python -m tools.trace_viewer_server --port 8000
```

**Providers**:
- FaaS: `ali_fc`, `aws_lambda`, `gcp_faas`
- Session-MCP: `ali_agentrun`, `aws_agentcore`, `gcp_mcp`
- External Gateway: `mcp_gateway`

## Architecture

### Core Concepts

**Trace Workflow**: Agent executions are captured as JSON traces (`trace-flow.json`) describing a DAG of nodes. Each node has:
- `id`: Unique identifier (0 is the start node)
- `name`: Trace node name
- `type`: current traces use `llm`, `logic`, and `tool_use`; legacy `sandbox` traces are unsupported
- `edge_to`: Array of outgoing edges with `id`, `params`, and `interval` (delay in ms)
- `time`: Execution time in milliseconds

**Node Types**:
- `tool_use`: External tool invocation; runtime routing comes from benchmark config + CLI provider
- `llm`: Simulated LLM calls (sleep for recorded duration)
- `logic`: Control flow nodes with no execution

### Directory Structure

```
benchmarks/           # Benchmark definitions
  legacy/             # Unsupported historical fixtures
  TravelPlanner/      # Multi-tool travel planning agent
  DataSciBench/       # Data science agent
  ...

atsuite_sdk/          # Tool SDK and in-container runtime wrappers
  abstract.py         # UnifiedAgentTool decorator/registry
  workflow.py         # Trace, Node, Edge dataclasses
  mcp_server.py       # MCP server wrapper
  function.py         # FaaS function wrapper

atsuite/                # Main package
  invoker.py          # Trace execution engine (topological sort)
  runtime.py          # RuntimeAdapter interfaces and concrete adapters
  scheduler.py        # FaaS access scheduler
  analyzer.py         # Analyzer v2 facade
  analysis/           # Events, provider collectors, pricing, aggregation, export
  deploy.py           # Provider deployment orchestration
  cli/                # First-class CLI implementations
  ali/                # Alibaba Cloud provider (FC, OSS, SLS)
  faas/               # FaaS client implementations
  mcp/                # MCP client implementations

tools/                # CLI tools
  build_docker_images.py  # Compatibility wrapper
  deploy.py               # Compatibility wrapper
  invoker.py              # Compatibility wrapper
  trace_viewer_server.py  # Compatibility wrapper

dockerfiles/          # Provider-specific Dockerfiles
  ali/                # Alibaba Cloud Function Compute
  aws_lambda/         # AWS Lambda
  aws_agentcore/      # AWS AgentCore
  gcp/                # Google Cloud
  mcp_gateway/        # External MCP-Gateway image
```

### Benchmark Structure

Each benchmark contains:
```
benchmarks/<name>/
  config/             # JSON deployment configs
    *.json           # Defines trace/name bindings + pipeline composition
  nodes/             # Node implementations
    <tool>/
      implementation.py   # Tool logic with @registry.tool() decorator
      requirements.txt    # Python dependencies
      mcp-config.json     # MCP-specific config
      function-config.json # FaaS-specific config
      init.sh            # Optional initialization script
  trace/             # Captured trace JSON files
```

**Config JSON format**:
```json
{
  "trace_file": "./trace/workflow.json",
  "nodes": [
    {
      "name": "flights",
      "dir": "./nodes/flights/",
      "trace_names": ["flights.run"]
    }
  ],
  "pipeline": {
    "faas": {
      "build": { "python_version": "3.11" },
      "deploy": { "cpu": 2, "memory": 2048, "disk": 512, "timeout": 30 },
      "units": [
        { "name": "flights", "node": "flights", "trace_names": ["flights.run"] }
      ]
    },
    "mcp_serverless": {
      "servers": [
        { "name": "travel_lookup", "nodes": ["flights"] }
      ]
    }
  }
}
```

### Key Implementation Patterns

**Creating a Tool**: Use the `@registry.tool()` decorator from `atsuite_sdk.abstract`:
```python
from atsuite_sdk.abstract import registry

@registry.tool()
def my_tool(param: str) -> str:
    """Tool description for MCP schema."""
    return result
```

**Building**: `tools/build_docker_images.py` resolves the selected pipeline from `config + --provider`, injects provider-owned `base_image` in code, and builds one image per deploy target.

**Deployment**: `atsuite/deploy.py` resolves the same target graph and deploys either FaaS units or MCP servers depending on `--provider`.

**Invocation**: `atsuite/invoker.py` loads the trace, routes each `tool_use` node through the resolved pipeline, and calls the deployed endpoint via clients in `atsuite/mcp/mcp.py` or `atsuite/faas/function.py`.

**Analysis**: `atsuite/analyzer.py` is a v2 facade over `atsuite.analysis`: replay records provider-neutral events, collectors join provider logs (Ali SLS, AWS CloudWatch, GCP Cloud Logging, or Gateway observability), pricing policies produce cost line items, and exporters write `*.events.json`, `*.report.json`, and `*.evidence.jsonl`.

### Legacy Sandbox

Sandbox/local runtime management has been removed. Historical sandbox-only traces live under `benchmarks/legacy/` and should be treated as unsupported fixtures until they are exposed through an external MCP-Gateway/router.
