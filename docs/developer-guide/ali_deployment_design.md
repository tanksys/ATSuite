# Alibaba Cloud Deployment Design

This note describes how the Alibaba Cloud SDK integration deploys ATSuite nodes.

## Supported Modes

### FaaS

ATSuite deploys a node to Alibaba Cloud Function Compute (FC). The deployment layer hides provider-specific details such as image push, function creation, trigger creation, and URL discovery.

### MCP

ATSuite deploys MCP services to FC as well. Stateful behavior is implemented with Alibaba Cloud OSS or another storage backend.

## Main Classes

### `atsuite/ali/ali.py`: `Ali`

`Ali` is the Alibaba Cloud platform entrypoint. It creates and manages cloud service clients and exposes high-level deployment methods.

Important methods:

- `get_fc_client()`: create and return an FC client.
- `deploy_function(**kwargs)`: create an `AliFC` object for FaaS deployment.
- `deploy_mcp(**kwargs)`: create an `AliFC` object for MCP deployment.

### `atsuite/ali/function.py`: `AliFC`

`AliFC` implements the function-level deployment flow on FC.

Important attributes include:

- `client`: initialized FC client.
- `typ`: deployment type.
- `url`: public trigger URL after deployment.
- `function_name`: FC function name.
- `entrypoint`: container entrypoint.
- `tag`: local Docker image tag.
- `runtime`: usually `custom-container`.
- `cpu`, `memory_size`, `timeout`, `disk_size`: resource configuration.
- `trigger_type` and `trigger_config`: HTTP trigger configuration.

Important methods:

- `deploy()`: run image push, function creation, trigger creation, and return the public URL.
- `create_acr(tag)`: push the local Docker image to ACR and return the remote image URL.
- `create_function(image)`: create the FC function with the remote image.
- `create_trigger()`: create the HTTP trigger and return its URL.

### `atsuite/faas/function.py`: `AliFunctionDeployer`

`AliFunctionDeployer` deploys benchmark nodes as FaaS functions. It reads node configuration, creates an `Ali` client, and calls `Ali.deploy_function()`.

### `atsuite/mcp/mcp.py`: `AliMCPDeployer`

`AliMCPDeployer` deploys benchmark nodes as MCP services. It follows the same high-level structure as `AliFunctionDeployer` but calls `Ali.deploy_mcp()`.

### `atsuite/ali/oss.py`: `AliOSS`

`AliOSS` implements storage operations for Alibaba Cloud OSS.

Important methods:

- `ensure_bucket_exists()`
- `upload(key, filepath)`
- `download(key, filepath)`
- `append(key, data)`
- `read(key)`
- `deleteobj(key)`
- `clearobj(key)`

### `atsuite/ali/sls.py`: `AliSLS`

`AliSLS` wraps Alibaba Cloud Log Service operations used for provider-side evidence collection.

Important methods:

- `create_project()`
- `create_logstore(logstore)`
- `create_index(logstore)`
- `getlogs(location, project, logstore)`

## External Usage

### FaaS

```python
function_deployer = AliFunctionDeployer(bench_name)
url = function_deployer.deploy_node(node_name, node_dir)
```

### MCP

```python
mcp_deployer = AliMCPDeployer(bench_name)
url = mcp_deployer.deploy_node(service_name, node_dir)
```

Stateful tool logic should instantiate the storage adapter and use it through the SDK abstraction.
