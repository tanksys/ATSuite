# ATSuite

![Main Idea](./pics/mainidea.png)

ATSuite is a framework for benchmarking AI agent infrastructure across different execution environments. It separates agent runtime behavior from LLM inference so you can measure how infrastructure choices affect end-to-end latency, cold starts, memory usage, and operating cost.

The project is built for agent workflows that use tools, MCP servers, and serverless functions. Instead of benchmarking model quality, ATSuite benchmarks the systems layer underneath the agent.

## Why ATSuite

Modern agents increasingly rely on external tools and execution runtimes such as MCP servers and FaaS platforms. In practice, these runtime choices can have a large impact on:

- End-to-end response time
- Cold start overhead
- Memory consumption
- Invocation and storage cost
- Stateful tool execution behavior

Most agent benchmarks focus on task accuracy. ATSuite focuses on the infrastructure dimension.

## How It Works

ATSuite follows a four-stage workflow:

1. Capture or prepare an agent trace as a workflow DAG.
2. Build each benchmark node into a target runtime form such as FaaS or Session-MCP.
3. Deploy the built artifacts to a selected provider.
4. Replay the trace and collect infrastructure metrics.

The workflow uses three main node types:

- `logic`: control-flow nodes
- `llm`: recorded LLM calls
- `tool_use`: external tool execution

## Core Capabilities

- Unified benchmark format for agent workflow traces
- Support for stateless tools and stateful tools through **Virtual Tool Service (VTS)** abstractions
- Deployment targets for state-decoupled way (known as FaaS), and state-coupled way (such as cloud Session-MCP, E2B)
- Replay engine for trace-driven benchmark execution
- Analysis tooling for latency, memory, cold starts, and cost

## Supported Providers and Modes

ATSuite currently works with these provider targets:

- `ali_fc`
  Alibaba Cloud Function Compute
- `ali_agentrun`
  Alibaba Cloud Session-MCP deployment
- `aws_lambda`
  AWS Lambda
- `aws_agentcore`
  AWS AgentCore Session-MCP deployment
- `gcp_faas`
  Google Cloud Functions style deployment
- `gcp_mcp`
  Google Cloud Session-MCP deployment
- `mcp_gateway`
  External MCP-Gateway/router deployment. ATSuite registers MCP server images and replays against the returned endpoint; sandbox lifecycle is managed outside this project.
  Set `MCP_GATEWAY_URL` and `MCP_GATEWAY_IMAGE_PREFIX` before deploying to this provider.

Provider-specific setup notes live under [`docs/userguide/`](./docs/userguide/), provider implementation notes live under [`docs/developer-guide/`](./docs/developer-guide/), and provider background notes live under [`docs/provider/`](./docs/provider/).

## Installation

ATSuite uses [uv](https://docs.astral.sh/uv/) for dependency management.

Prerequisites:

- Python 3.12+
- `uv`
- Docker
- Cloud or gateway credentials for the provider you want to use

Install the default dependency set:

```bash
uv sync --group aliyun
```

Install additional provider dependencies as needed:

```bash
uv sync --group aws
uv sync --group gcp
```

## Quickstart

The basic workflow is build, deploy, then replay a trace.

### 1. Build benchmark images

```bash
uv run python -m tools.build_docker_images \
  --config benchmarks/TravelPlanner/config/faas7_mcp2_min.json \
  --provider aws_lambda
```

### 2. Deploy the benchmark

```bash
uv run python -m tools.deploy \
  --config benchmarks/TravelPlanner/config/faas7_mcp2_min.json \
  --provider aws_lambda
```

### 3. Replay the trace

```bash
uv run python -m tools.invoker \
  --config benchmarks/TravelPlanner/config/faas7_mcp2_min.json \
  --url-map url_results/faas7_mcp2_min.json \
  --provider aws_lambda \
  --uid demo
```

## CLI Reference

Build images:

```bash
uv run python -m tools.build_docker_images --help
```

Deploy to a provider:

```bash
uv run python -m tools.deploy --help
```

Replay a trace:

```bash
uv run python -m tools.invoker --help
```

Start the trace viewer:

```bash
uv run python -m tools.trace_viewer_server --port 8000
```

## Repository Layout

```text
benchmarks/           Benchmark definitions, node code, configs, and traces
atsuite_sdk/           Tool SDK and in-container runtime wrappers
atsuite/                Main runtime, deployment, provider, and analysis code
  analysis/           Analyzer v2: events, collectors, pricing, aggregation, export
  cli/                First-class command implementations
tools/                Compatibility CLI wrappers
dockerfiles/          Provider-specific container build templates
docs/                 ATG docs, user guides, provider notes, and implementation notes
web/trace_viewer/     Browser-based trace viewer
benchmarks/legacy/    Unsupported(still in progress) legacy workloads, including sandbox-only traces
```

## Benchmarks Included

The repository includes several benchmark workloads, including:

- `TravelPlanner`: tool-using travel planning workload
- `DataSciBench`: data science and state-heavy workflows
- `ScientificComputation`: scientific tool workflow benchmark
- `ClaudeCodeReview`: replayable code-review benchmark

Each benchmark directory contains its own configs, node implementations, traces, and any benchmark-specific instructions.

## Benchmark Structure

Each benchmark typically looks like this:

```text
benchmarks/<name>/
  config/             Deployment and pipeline configuration
  nodes/              Tool implementations
  trace/              Captured workflow traces
  README.md           Benchmark-specific notes
```

A config file maps benchmark nodes to runtime targets and provider-specific deployment units.

## Trace Inputs

ATSuite replays prepared workflow traces. A trace is a JSON DAG made of `logic`, `llm`, and `tool_use` nodes. Legacy `sandbox` traces are kept under `benchmarks/legacy/` only as historical fixtures and are not supported by the current runtime path.

## Documentation

Useful starting points:

- [`docs/atg/workflow_spec.md`](./docs/atg/workflow_spec.md): workflow DAG format
- [`docs/atg/node_config.md`](./docs/atg/node_config.md): benchmark node and pipeline configuration
- [`docs/userguide/aws.md`](./docs/userguide/aws.md): AWS setup and deployment guide
- [`docs/userguide/gcp.md`](./docs/userguide/gcp.md): GCP setup and deployment guide
- [`docs/userguide/ali.md`](./docs/userguide/ali.md): Alibaba Cloud setup and deployment guide
- [`docs/developer-guide/ali_deployment_design.md`](./docs/developer-guide/ali_deployment_design.md): Alibaba Cloud deployment implementation notes
- [`docs/provider/overview.md`](./docs/provider/overview.md): cloud service map
- [`web/trace_viewer/README.md`](./web/trace_viewer/README.md): trace viewer usage

## Creating New Benchmark Nodes

ATSuite exposes tool definitions through the registry in `atsuite_sdk.abstract`. A typical tool implementation looks like this:

```python
from atsuite_sdk.abstract import registry


@registry.tool()
def my_tool(param: str) -> str:
    """Tool description used in generated schemas."""
    return "result"
```

To convert an existing agent tool into an ATSuite node layout, see [`docs/atg/tool_conversion.md`](./docs/atg/tool_conversion.md).

## Current Scope

ATSuite is an active benchmarking framework rather than a polished end-user platform. Some documentation is still provider-specific or benchmark-specific, and parts of the repository reflect ongoing evaluation work. The top-level flow, however, is stable:

1. Prepare a trace
2. Build the runtime artifacts
3. Deploy to a target provider
4. Replay and analyze

Analyzer v2 writes three artifacts under `results/<provider>/<benchmark>/`:
`*.events.json` for provider-neutral replay observations, `*.report.json` for
the normalized `schema_version=2` report, and `*.evidence.jsonl` for full raw
provider evidence collected from SLS, CloudWatch, Cloud Logging, or Gateway
observability.
