import os
from pathlib import Path
from typing import Dict, Optional

from atsuite.pipeline import CliOverrides, is_sandbox_config, resolve_benchmark, target_image_tag
from atsuite.runtime import GatewayClient
from atsuite.utils import write_url_map


def deploy(
    config_path: Path,
    provider: str,
    *,
    runtime: Optional[str] = None,
) -> Optional[Path]:
    if is_sandbox_config(config_path):
        raise SystemExit("Sandbox configs are no longer supported; use an external MCP-Gateway target instead")

    resolved = resolve_benchmark(config_path, provider, CliOverrides())
    endpoint_cache: Dict[str, Dict[str, object]] = {}

    if provider == "mcp_gateway":
        gateway = GatewayClient()
        for target in resolved.targets.values():
            print(f"[deploy] Registering gateway target: '{target.name}'")
            manifest = {"allowed_tools": list(_allowed_tools_for_target(resolved.nodes, target))}
            endpoint = gateway.register_target(
                name=target.name,
                image=_gateway_image_ref(resolved.bench_name, target),
                resources=target.runtime.to_dict(),
                manifest=manifest,
            )
            endpoint_cache[target.name] = _endpoint_entry(endpoint, target, manifest)
        payload = {
            "provider": provider,
            "family": resolved.family,
            "targets": endpoint_cache,
        }
        output_path = write_url_map(config_path, payload)
        print(f"[deploy] URLs saved to {output_path}")
        print(f"[deploy] Registered {len(endpoint_cache)} target(s)")
        return output_path

    function_deployer = None
    mcp_deployer = None
    if resolved.family == "faas":
        if provider == "ali_fc":
            from atsuite.faas.function import AliFunctionDeployer
            function_deployer = AliFunctionDeployer(resolved.bench_name)
        elif provider == "aws_lambda":
            from atsuite.faas.function import AWSFunctionDeployer
            function_deployer = AWSFunctionDeployer(resolved.bench_name)
        elif provider == "gcp_faas":
            from atsuite.faas.function import GCPFunctionDeployer
            function_deployer = GCPFunctionDeployer(resolved.bench_name)
        else:
            raise SystemExit(f"Unsupported FaaS provider: {provider}")
    else:
        if provider == "ali_agentrun":
            from atsuite.mcp.mcp import AliMCPDeployer
            mcp_deployer = AliMCPDeployer(resolved.bench_name)
        elif provider == "aws_agentcore":
            from atsuite.mcp.mcp import AWSAgentCoreMCPDeployer
            mcp_deployer = AWSAgentCoreMCPDeployer(resolved.bench_name)
        elif provider == "gcp_mcp":
            from atsuite.mcp.mcp import GCPMCPDeployer
            mcp_deployer = GCPMCPDeployer(resolved.bench_name)
        else:
            raise SystemExit(f"Unsupported MCP provider: {provider}")

    for target in resolved.targets.values():
        if target.family == "faas":
            print(f"[deploy] Deploying function target: '{target.name}'")
            url = function_deployer.deploy_target(target.name, target.runtime)
        else:
            print(f"[deploy] Deploying mcp target: '{target.name}'")
            url = mcp_deployer.deploy_target(target.name, target.runtime)
        if url is not None:
            endpoint_cache[target.name] = _endpoint_entry(
                url.rstrip("/"),
                target,
                {"allowed_tools": list(_allowed_tools_for_target(resolved.nodes, target))},
            )

    payload = {
        "provider": provider,
        "family": resolved.family,
        "targets": endpoint_cache,
    }
    output_path = write_url_map(config_path, payload)
    print(f"[deploy] URLs saved to {output_path}")
    print(f"[deploy] Deployed {len(endpoint_cache)} target(s)")
    return output_path


def _endpoint_entry(url: str, target, manifest: Dict[str, object]) -> Dict[str, object]:
    return {
        "endpoint": url.rstrip("/"),
        "family": target.family,
        "resources": target.runtime.to_dict(),
        "tool_manifest": manifest,
    }


def _gateway_image_ref(bench_name: str, target) -> str:
    image = target_image_tag(bench_name, target)
    prefix = os.environ.get("MCP_GATEWAY_IMAGE_PREFIX", "").strip().rstrip("/")
    if prefix:
        return f"{prefix}/{image}"
    if "/" in image:
        return image
    raise RuntimeError(
        "MCP_GATEWAY_IMAGE_PREFIX is required for mcp_gateway deploy so the Gateway can pull the image"
    )


def _allowed_tools_for_target(nodes, target) -> tuple[str, ...]:
    if target.family == "faas":
        return tuple(target.allowed_tools)
    tools = []
    for node_name in target.node_names:
        node = nodes[node_name]
        for trace_name in node.trace_names:
            tools.append(node.tool_name_for_trace(trace_name))
    return tuple(dict.fromkeys(tools))
