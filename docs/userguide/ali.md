# Alibaba Cloud Deployment Guide

This guide shows how to deploy ATSuite nodes to Alibaba Cloud in FaaS and MCP modes.

## 1. FaaS

The example below uses `benchmarks/soccer/config/detect_league_function.json`.

### 1. Prepare Credentials and Registry

Prepare:

- Alibaba Cloud AccessKey ID and AccessKey Secret.
- Function Compute endpoint.
- Alibaba Cloud Container Registry (ACR) repository address.

Add the following environment variables to your shell profile:

```text
export ALIBABA_CLOUD_ACCESS_KEY_ID="your AccessKey ID"
export ALIBABA_CLOUD_ACCESS_KEY_SECRET="your AccessKey Secret"
export ALI_ENDPOINT="your FC endpoint"
export ACR_NAME="your ACR repository address"
```

Then reload the profile:

```bash
source ~/.bashrc
```

### 2. Build the Image

Run from the repository root:

```bash
uv run -m tools.build_docker_images \
  --config benchmarks/soccer/config/detect_league_function.json \
  --provider ali_fc
```

### 3. Deploy

```bash
uv run -m tools.deploy \
  --config benchmarks/soccer/config/detect_league_function.json \
  --provider ali_fc
```

If this is the first time using ACR, log in first:

```bash
docker login --username="your Alibaba Cloud account name" "registry domain"
```

After deployment, ATSuite writes the HTTP trigger URL to `url_results/detect_league_function.json`.

### 4. Invoke

```bash
uv run -m tools.invoker \
  --config benchmarks/soccer/config/detect_league_function.json \
  --url-map url_results/detect_league_function.json \
  --provider ali_fc \
  --uid abc
```

If node execution logs appear in order, the deployment is working.

## 2. MCP

The example below uses `benchmarks/TravelPlanner/config/notebook_mcp.json`.

### 1. Configure OSS

MCP mode may need storage for stateful tools. Enable OSS and set:

```text
export OSS_ACCESS_KEY_ID="your AccessKey ID"
export OSS_ACCESS_KEY_SECRET="your AccessKey Secret"
```

Reload the shell profile:

```bash
source ~/.bashrc
```

### 2. Build

```bash
uv run -m tools.build_docker_images \
  --config benchmarks/TravelPlanner/config/notebook_mcp.json \
  --provider ali_agentrun
```

### 3. Deploy

```bash
uv run -m tools.deploy \
  --config benchmarks/TravelPlanner/config/notebook_mcp.json \
  --provider ali_agentrun
```

The service URL is written to `url_results/notebook_mcp.json`.

### 4. Invoke

```bash
uv run -m tools.invoker \
  --config benchmarks/TravelPlanner/config/notebook_mcp.json \
  --url-map url_results/notebook_mcp.json \
  --provider ali_agentrun \
  --uid abc
```

Use a stable `uid` when testing stateful MCP tools.
