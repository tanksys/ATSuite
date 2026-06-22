# AWS 部署指南

本文档介绍如何在 AWS 上部署 Function 和 MCP 服务。

---

## 📋 快速开始

### 1. 安装依赖

```bash
uv sync --group aws
```

### 2. 配置 AWS

首先需要安装 aws cli，之后输入命令：

```bash
aws configure
# 输入：Access Key ID, Secret Access Key, Region (us-east-1), Output (json)
```

### 3. 设置环境变量

创建 `.env` 文件：

```bash
AWS_ACCOUNT_ID=123456789012
AWS_REGION=us-east-1
ECR_REPOSITORY_NAME=atsuite-mcp

# Lambda 需要
AWS_LAMBDA_ROLE_ARN=arn:aws:iam::123456789012:role/atsuite-lambda-execution-role

# AgentCore 需要
AWS_AGENTCORE_ROLE_ARN=arn:aws:iam::123456789012:role/atsuite-agentcore-execution-role
```

---

## 🚀 部署 Function

### 构建镜像

```bash
uv run -m tools.build_docker_images \
  --config benchmarks/soccer/config/detect_league_function.json \
  --provider aws_lambda
```

### 部署到 Lambda

```bash
uv run -m tools.deploy \
  --config benchmarks/soccer/config/detect_league_function.json \
  --provider aws_lambda
```


---

## 🔧 部署 MCP

通过 `--provider` 参数区分两种部署模式：

| 模式 | Provider 参数 | 认证 |
|------|--------------|------|
| **Lambda** | `aws_lambda` |  公开访问 |
| **AgentCore** | `aws_agentcore` | AWS SigV4 |

### Lambda 模式

**配置** (`mcp-config.json`):
```json
{
  "name": "my_mcp",
  "memory": 1024,
  "timeout": 30
}
```

**构建  部署**:
```bash
uv run -m tools.build_docker_images \
  --config benchmarks/TravelPlanner/config/task0_all_mcp.json \
  --provider aws_lambda

uv run -m tools.deploy \
  --config benchmarks/TravelPlanner/config/task0_all_mcp.json \
  --provider aws_lambda
```


---

### AgentCore 模式

> AgentCore 镜像必须为 `linux/arm64` 平台
> 本地为 x86 机器，构建需要 QEMU 支持，要执行：
> ```bash
> docker run --rm --privileged multiarch/qemu-user-static --reset -p yes
> ```


**构建镜像**:
```bash
uv run -m tools.build_docker_images \
  --config benchmarks/TravelPlanner/config/task0_all_mcp.json \
  --provider aws_agentcore
```

**部署到 AgentCore**:
```bash
uv run -m tools.deploy \
  --config benchmarks/TravelPlanner/config/task0_all_mcp.json \
  --provider aws_agentcore
```

部署成功后，URL 自动保存到 `url_results/task0_all_mcp.json`。



