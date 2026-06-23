# GCP Deployment and Testing Guide

## 1. Environment Variables

GCP-related code reads the following environment variables. Configure them either in the shell or in a local `.env` file.

- `GOOGLE_CLOUD_PROJECT`: GCP project ID used by `gcloud`, Cloud Logging, and Cloud Storage.
- `GCP_REGION`: deployment region. Defaults to `us-central1`.
- `GCP_BUCKET`: GCS bucket used by deployed Cloud Run services.
- `GOOGLE_APPLICATION_CREDENTIALS`: service account credential path for local ADC. If using `gcloud auth application-default login`, this can be omitted.
- `GCP_IMAGE_PREFIX`: optional Artifact Registry prefix. If omitted, ATSuite uses `gcr.io/<project_id>/...`.
- `FC_SERVER_PORT`: function container port. Cloud Run usually uses `8080`.
- `ATSUITE_MCP_PORT`: MCP container port. Cloud Run usually uses `8080`.
- `ATSUITE_MCP_PATH`: MCP endpoint path. Defaults to `/mcp`.
- `ATSUITE_MCP_NAME`: MCP service name used by FastMCP inside the container.

Minimal setup:

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
export GCP_REGION=us-central1
export GCP_BUCKET=your-bucket-name
gcloud auth application-default login
gcloud auth configure-docker gcr.io
```

## 2. Install Dependencies

GCP dependencies are defined in the `gcp` dependency group:

```bash
uv sync --group gcp
```

The group includes packages such as:

- `google-cloud-storage`
- `google-cloud-logging`
- `google-cloud-monitoring`
- `google-cloud-workflows`
- `google-cloud-datastore`
- `google-api-python-client`
- `google-auth`

The main project dependencies also require `requests`, `python-dotenv`, `fastmcp`, and `mcp`.

## 3. Main Classes

### `atsuite/gcp/gcp.py`: `GCP`

The `GCP` class is the platform entrypoint. It manages project and region configuration and exposes Storage and Cloud Run deployment operations through `deploy_function()` and `deploy_mcp()`.

### `atsuite/gcp/fc.py`: `GCPFC`

`GCPFC` implements Cloud Run deployment. It tags a local image, pushes it to the registry, runs `gcloud run deploy`, and returns the service URL. Function and MCP services share the same flow and are distinguished by `typ`.

### `atsuite/faas/function.py` and `atsuite/mcp/mcp.py`

`GCPFunctionDeployer` and `GCPMCPDeployer` read node configuration and call `GCP.deploy_function()` or `GCP.deploy_mcp()`.

## 4. Deployment Flow

Using `benchmarks/gcp_demo/config/function.json` as an example:

1. Install dependencies:

```bash
uv sync --group gcp
```

2. Set at least `GOOGLE_CLOUD_PROJECT`, `GCP_REGION`, and `GCP_BUCKET`.

3. Authenticate:

```bash
gcloud auth application-default login
gcloud auth configure-docker gcr.io
```

4. Build the image:

```bash
uv run -m tools.build_docker_images \
  --config benchmarks/gcp_demo/config/function.json \
  --provider gcp_faas
```

5. Deploy:

```bash
uv run -m tools.deploy \
  --config benchmarks/gcp_demo/config/function.json \
  --provider gcp_faas
```

6. Replay the trace:

```bash
uv run -m tools.invoker \
  --config benchmarks/gcp_demo/config/function.json \
  --url-map url_results/function.json \
  --provider gcp_faas \
  --uid gcp-test-user
```

For MCP, use `config/mcp.json` and the corresponding MCP provider. The `just gcp-function` and `just gcp-mcp` shortcuts can run the build, deploy, and replay flow when configured.
