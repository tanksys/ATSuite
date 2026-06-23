# GCP 部署与测试

---

## 1. 需要的环境变量

GCP 相关代码会直接读取下面这些变量，建议本地 `.env` 和终端环境都准备好。

- `GOOGLE_CLOUD_PROJECT`：GCP 项目 ID，`gcloud`、Cloud Logging、Cloud Storage 都会用到。
- `GCP_REGION`：部署区域，默认 `us-central1`。
- `GCP_BUCKET`：Cloud Run 服务里实际使用的 GCS bucket 名，建议显式设置，避免误回退到项目 ID。
- `GOOGLE_APPLICATION_CREDENTIALS`：本地使用 ADC 时的服务账号凭据路径；如果你用 `gcloud auth application-default login`，也可以不手动设置。
- `GCP_IMAGE_PREFIX`：可选，Artifact Registry 前缀；不设置时默认走 `gcr.io/<project_id>/...`。
- `FC_SERVER_PORT`：Function 容器端口，Cloud Run 场景下通常由部署脚本设置为 `8080`。
- `ATSUITE_MCP_PORT`：MCP 容器端口，Cloud Run 场景下通常由部署脚本设置为 `8080`。
- `ATSUITE_MCP_PATH`：MCP 路径，默认 `/mcp`。
- `ATSUITE_MCP_NAME`：MCP 服务名称，主要用于容器内 FastMCP 命名。

最小可用示例：

```bash
export GOOGLE_CLOUD_PROJECT=你的项目 ID
export GCP_REGION=us-central1
export GCP_BUCKET=你的 bucket 名
gcloud auth application-default login
gcloud auth configure-docker gcr.io
```

---

## 2. 依赖安装

GCP 相关能力已经放在 `pyproject.toml` 的 `gcp` dependency group 里，重新测试前建议执行：

```bash
uv sync --group gcp
```

这组依赖主要包含：

- `google-cloud-storage`
- `google-cloud-logging`
- `google-cloud-monitoring`
- `google-cloud-workflows`
- `google-cloud-datastore`
- `google-api-python-client`
- `google-auth`

项目主依赖里还需要：

- `requests`
- `python-dotenv`
- `fastmcp`
- `mcp`

---

## 3. 类简介

### (1) `atsuite/gcp/gcp.py` 中的 `GCP` 类

`GCP` 类是 GCP 平台的接入入口，负责 project/region 配置及 Storage、Cloud Run 的部署接口。提供 `deploy_function()` 和 `deploy_mcp()` 方法。

### (2) `atsuite/gcp/fc.py` 中的 `GCPFC` 类

`GCPFC` 实现 Cloud Run 部署：本地镜像 tag → push 到 GCR → `gcloud run deploy`，返回服务 URL。Function 和 MCP 共用此流程，通过 `typ` 区分（环境变量 `FC_SERVER_PORT` / `ATSUITE_MCP_PORT`）。服务名会经 `_cloud_run_service_name()` 转为合法格式（下划线→连字符）。

### (3) `atsuite/faas/function.py` 中的 `GCPFunctionDeployer` 与 `atsuite/mcp/mcp.py` 中的 `GCPMCPDeployer`

分别封装 function 和 mcp 的部署逻辑，读取节点配置后调用 `GCP.deploy_function()` / `GCP.deploy_mcp()` 完成部署。

---

## 4. 部署流程

以 `benchmarks/gcp_demo/config/function.json` 为例：

1. 安装依赖：`uv sync --group gcp`
2. 设置环境变量：至少要有 `GOOGLE_CLOUD_PROJECT`、`GCP_REGION`、`GCP_BUCKET`
3. 认证：`gcloud auth application-default login`；`gcloud auth configure-docker gcr.io`
4. 构建镜像：`uv run -m tools.build_docker_images --config benchmarks/gcp_demo/config/function.json --provider gcp_faas`
5. 部署：`uv run -m tools.deploy --config benchmarks/gcp_demo/config/function.json --provider gcp_faas`
6. 重放 trace：`uv run -m tools.invoker --config benchmarks/gcp_demo/config/function.json --url-map url_results/function.json --provider gcp_faas --uid gcp-test-user`

或使用 just：`just gcp-function`（一键构建→部署→重放）。

MCP 同理，使用 `config/mcp.json`、`just gcp-mcp`。
