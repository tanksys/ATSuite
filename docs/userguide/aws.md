# AWS Deployment Guide

This guide explains how to deploy ATSuite Function and MCP services on AWS.

## Quick Start

### 1. Install Dependencies

```bash
uv sync --group aws
```

### 2. Configure AWS

Install the AWS CLI, then run:

```bash
aws configure
# Enter: Access Key ID, Secret Access Key, Region (for example us-east-1), Output (json)
```

### 3. Set Environment Variables

Create a `.env` file:

```text
AWS_ACCOUNT_ID=123456789012
AWS_REGION=us-east-1
ECR_REPOSITORY_NAME=atsuite-mcp

# Required by Lambda
AWS_LAMBDA_ROLE_ARN=arn:aws:iam::123456789012:role/atsuite-lambda-execution-role

# Required by AgentCore
AWS_AGENTCORE_ROLE_ARN=arn:aws:iam::123456789012:role/atsuite-agentcore-execution-role
```

## Deploy Function

Build the image:

```bash
uv run -m tools.build_docker_images \
  --config benchmarks/soccer/config/detect_league_function.json \
  --provider aws_lambda
```

Deploy to Lambda:

```bash
uv run -m tools.deploy \
  --config benchmarks/soccer/config/detect_league_function.json \
  --provider aws_lambda
```

## Deploy MCP

Use `--provider` to select the deployment mode:

| Mode | Provider | Authentication |
|---|---|---|
| Lambda | `aws_lambda` | Public access |
| AgentCore | `aws_agentcore` | AWS SigV4 |

### Lambda Mode

Example `mcp-config.json`:

```json
{
  "name": "my_mcp",
  "memory": 1024,
  "timeout": 30
}
```

Build and deploy:

```bash
uv run -m tools.build_docker_images \
  --config benchmarks/TravelPlanner/config/task0_all_mcp.json \
  --provider aws_lambda

uv run -m tools.deploy \
  --config benchmarks/TravelPlanner/config/task0_all_mcp.json \
  --provider aws_lambda
```

### AgentCore Mode

AgentCore images must be built for `linux/arm64`. On an x86 machine, enable QEMU first:

```bash
docker run --rm --privileged multiarch/qemu-user-static --reset -p yes
```

Build:

```bash
uv run -m tools.build_docker_images \
  --config benchmarks/TravelPlanner/config/task0_all_mcp.json \
  --provider aws_agentcore
```

Deploy:

```bash
uv run -m tools.deploy \
  --config benchmarks/TravelPlanner/config/task0_all_mcp.json \
  --provider aws_agentcore
```

After deployment, the URL is written to `url_results/task0_all_mcp.json`.
