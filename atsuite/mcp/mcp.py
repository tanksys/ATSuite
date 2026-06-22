import json
import os
import threading
import uuid
from pathlib import Path
from typing import Optional

import httpx
import requests
import time

from atsuite.utils import normalize_node_name
from atsuite.mcp.config import load_mcp_config, mcp_config_path
from atsuite.pipeline import RuntimeConfig
import logging

logging.getLogger("httpx").setLevel(logging.WARNING)

_MCP_CLIENT_TIMEOUT_SECONDS = 3600.0


def _extract_mcp_tool_error_message(response_payload: Optional[dict]) -> Optional[str]:
    if not isinstance(response_payload, dict):
        return None

    result = response_payload.get("result")
    if not (isinstance(result, dict) and result.get("isError")):
        return None

    content = result.get("content")
    if isinstance(content, list):
        texts = [
            item.get("text")
            for item in content
            if isinstance(item, dict) and item.get("text")
        ]
        if texts:
            return " | ".join(str(text) for text in texts)

    error_value = result.get("error")
    if error_value:
        return str(error_value)
    return str(result)


def _log_mcp_tool_error(
    response_payload: Optional[dict], *, client_name: str, tool_name: str
) -> None:
    error_message = _extract_mcp_tool_error_message(response_payload)
    if error_message:
        print(f"[{client_name}] Tool returned isError for {tool_name}: {error_message}")


class MCPClient:
    def __init__(self, url: str, uid: str = ""):
        self.url = url.rstrip("/")
        self.uid = uid
        self.session_id = None
        self.initialize_request_id = None
        self._initialized = False
        self._init_lock = threading.Lock()
        self._http_client = httpx.Client(
            limits=httpx.Limits(max_connections=500, max_keepalive_connections=500),
            timeout=httpx.Timeout(_MCP_CLIENT_TIMEOUT_SECONDS),
        )
        print(f"[MCPClient] Created instance for url={self.url}, uid={uid}")

    @staticmethod
    def _raise_if_mcp_error(response_payload: Optional[dict]) -> None:
        if not isinstance(response_payload, dict):
            return
        if "error" in response_payload:
            raise RuntimeError(f"MCP error: {response_payload['error']}")

    def invoke(self, tool_name: str, arguments: dict, request_id: Optional[str] = None):
        if not self._initialized:
            with self._init_lock:
                if not self._initialized:
                    print(f"[MCPClient] Initializing for {self.url}, tool={tool_name}")
                    self._initialize_internal(request_id=request_id)
                    print(f"[MCPClient] Initialized, session_id={self.session_id}")

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        if request_id:
            headers["X-Request-Id"] = request_id

        thread_id = threading.current_thread().ident
        call_time = int(time.time() * 1000)
        print(
            f"[MCPClient] Invoke tool={tool_name}, url={self.url}, session_id={self.session_id}, thread={thread_id}"
        )
        resp = self._http_client.post(
            f"{self.url}/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": f"call-{call_time}-{thread_id}",
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments,
                },
            },
        )
        if resp.status_code >= 500:
            print(
                f"[MCPClient] Server error {resp.status_code} for {self.url}, session_id={self.session_id}"
            )
            raise httpx.HTTPStatusError(
                f"Server error {resp.status_code}",
                request=resp.request,
                response=resp,
            )
        resp.raise_for_status()

        response_payload = self._read_streamable_response(resp)
        self._raise_if_mcp_error(response_payload)
        _log_mcp_tool_error(
            response_payload,
            client_name=self.__class__.__name__,
            tool_name=tool_name,
        )

        request_id = (
            resp.headers.get("X-Fc-Request-Id")
            or resp.headers.get("x-amzn-requestid")
            or request_id
        )
        return request_id

    def _read_streamable_response(self, response) -> Optional[dict]:
        content_type = response.headers.get("Content-Type", "").lower()
        if content_type.startswith("application/json"):
            body = response.read() if hasattr(response, "read") else response.content
            if isinstance(body, bytes):
                body = body.decode("utf-8")
            return json.loads(body) if body else None

        if not content_type.startswith("text/event-stream"):
            return None

        last_message = None
        for raw_line in response.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            if not line.startswith("data:"):
                continue
            data = line[len("data:") :].strip()
            if not data:
                continue
            payload = json.loads(data)
            last_message = payload
            if "error" in payload:
                raise RuntimeError(f"Local MCP error: {payload['error']}")
            if "result" in payload:
                return payload
        return last_message

    def _initialize_internal(self, request_id: Optional[str] = None):
        thread_id = threading.current_thread().ident
        print(
            f"[MCPClient._init] Starting initialization for url={self.url}, uid={self.uid}, thread={thread_id}"
        )
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if request_id:
            headers["X-Request-Id"] = request_id
        resp = self._http_client.post(
            f"{self.url}/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": "init-1",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "clientInfo": {"name": "local-test", "version": "0.1"},
                    "capabilities": {},
                },
            },
        )
        print(
            f"[MCPClient._init] Response status={resp.status_code}, url={self.url}, uid={self.uid}"
        )
        if resp.status_code >= 500:
            print(
                f"[MCPClient._init] Server error {resp.status_code}, body={resp.text[:200]}, url={self.url}, uid={self.uid}"
            )
        resp.raise_for_status()
        self.initialize_request_id = resp.headers.get(
            "X-Fc-Request-Id"
        ) or resp.headers.get("x-amzn-requestid")
        self.session_id = resp.headers.get("Mcp-Session-Id")
        print(
            f"[MCPClient._init] Success session_id={self.session_id}, url={self.url}, uid={self.uid}, thread={thread_id}"
        )
        self._initialized = True

    def initialize(self, request_id: Optional[str] = None):
        thread_id = threading.current_thread().ident
        if self._initialized:
            print(
                f"[MCPClient.init] Already initialized, url={self.url}, uid={self.uid}, session_id={self.session_id}, thread={thread_id}"
            )
            return self.initialize_request_id
        with self._init_lock:
            if not self._initialized:
                print(
                    f"[MCPClient.init] Calling _init_internal, url={self.url}, uid={self.uid}, thread={thread_id}"
                )
                self._initialize_internal(request_id)
            else:
                print(
                    f"[MCPClient.init] Initialized by another thread, url={self.url}, uid={self.uid}, session_id={self.session_id}, thread={thread_id}"
                )
        return self.initialize_request_id

    def get_initialize_request_id(self) -> Optional[str]:
        return self.initialize_request_id


class LocalMCPClient(MCPClient):
    def __init__(self, url: str, uid: str):
        super().__init__(url)
        self.uid = uid
        self.protocol_version = None

    def _build_headers(self, request_id: Optional[str] = None) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "X-ATSUITE-UID": self.uid,
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        if self.protocol_version:
            headers["mcp-protocol-version"] = self.protocol_version
        if request_id:
            headers["X-Request-Id"] = request_id
        return headers

    def _post_notification(self, method: str, params: Optional[dict] = None) -> None:
        resp = httpx.post(
            f"{self.url}/mcp",
            headers=self._build_headers(),
            json={
                "jsonrpc": "2.0",
                "method": method,
                **({"params": params} if params else {}),
            },
        )
        resp.raise_for_status()

    def invoke(self, tool_name: str, arguments: dict, request_id: Optional[str] = None):
        if not self._initialized:
            self.initialize(request_id=request_id)

        with httpx.stream(
            "POST",
            f"{self.url}/mcp",
            headers=self._build_headers(request_id=request_id),
            json={
                "jsonrpc": "2.0",
                "id": f"call-{uuid.uuid4().hex}",
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments,
                },
            },
            timeout=60.0,
        ) as resp:
            resp.raise_for_status()
            response_payload = self._read_streamable_response(resp)
            MCPClient._raise_if_mcp_error(response_payload)
            _log_mcp_tool_error(
                response_payload,
                client_name=self.__class__.__name__,
                tool_name=tool_name,
            )
            request_id = (
                resp.headers.get("X-Fc-Request-Id")
                or resp.headers.get("x-amzn-requestid")
                or request_id
            )
        return request_id

    def initialize(self, request_id: Optional[str] = None):
        with httpx.stream(
            "POST",
            f"{self.url}/mcp",
            headers=self._build_headers(request_id=request_id),
            json={
                "jsonrpc": "2.0",
                "id": "init-1",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "clientInfo": {"name": "local-test", "version": "0.1"},
                    "capabilities": {},
                },
            },
            timeout=60.0,
        ) as resp:
            resp.raise_for_status()
            payload = self._read_streamable_response(resp) or {}
            self.initialize_request_id = (
                resp.headers.get("X-Fc-Request-Id")
                or resp.headers.get("x-amzn-requestid")
                or request_id
            )
            self.session_id = resp.headers.get("Mcp-Session-Id")
            result = payload.get("result") if isinstance(payload, dict) else None
            if isinstance(result, dict):
                protocol_version = result.get("protocolVersion")
                if protocol_version:
                    self.protocol_version = str(protocol_version)
        self._post_notification("notifications/initialized")
        self._initialized = True
        return self.initialize_request_id


class AgentCoreMCPClient:
    """由于agentcore不能公开访问，需要客户端进行签名访问"""

    def __init__(self, url: str, region: str = None):
        self.url = url.rstrip("/")
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self.transport = (
            os.environ.get("ATSUITE_AGENTCORE_MCP_TRANSPORT", "http-streamable")
            .strip()
            .lower()
        )
        self._request_id = 0
        self._initialized = False
        self.initialize_request_id = None
        self.session_id = None  # 添加session_id支持，用于复用session
        self.protocol_version = None

        # 初始化 SigV4 凭证
        from botocore.session import Session as BotocoreSession

        session = BotocoreSession()
        self._credentials = session.get_credentials().get_frozen_credentials()

    def initialize(self, request_id: Optional[str] = None):
        """保持旧的简化路径：不单独发送 initialize，请求时再复用服务端返回的 session。"""
        if self._initialized:
            return self.initialize_request_id

        self._initialized = True
        return self.initialize_request_id

    def _read_response_payload(self, response) -> Optional[dict]:
        content_type = response.headers.get("Content-Type", "").lower()
        if content_type.startswith("application/json"):
            try:
                return response.json()
            except ValueError:
                return None

        # Backward-compatible fallback: some deployments may still emit SSE.
        if not content_type.startswith("text/event-stream"):
            return None

        body = response.text if hasattr(response, "text") else ""
        last_message = None
        for raw_line in body.splitlines():
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            if not line.startswith("data:"):
                continue
            data_str = line[len("data:") :].strip()
            if not data_str:
                continue
            try:
                payload = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            last_message = payload
            if "result" in payload or "error" in payload:
                return payload
        return last_message

    def _read_streamable_response(self, response) -> Optional[dict]:
        content_type = response.headers.get("Content-Type", "").lower()
        if content_type.startswith("application/json"):
            body = response.read() if hasattr(response, "read") else response.content
            if isinstance(body, bytes):
                body = body.decode("utf-8")
            return json.loads(body) if body else None

        if not content_type.startswith("text/event-stream"):
            return None

        last_message = None
        for raw_line in response.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            if not line.startswith("data:"):
                continue
            data = line[len("data:") :].strip()
            if not data:
                continue
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue
            last_message = payload
            if "result" in payload or "error" in payload:
                return payload
        return last_message

    @staticmethod
    def _raise_if_mcp_error(response_payload: Optional[dict]) -> None:
        if not isinstance(response_payload, dict):
            return
        if "error" in response_payload:
            raise RuntimeError(f"AgentCore MCP error: {response_payload['error']}")

    def _post_signed_request(
        self,
        payload: str,
        accept: str,
        *,
        include_session: bool = True,
        request_id: Optional[str] = None,
    ):
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest

        sign_headers = {
            "Content-Type": "application/json",
            "Accept": accept,
        }
        if request_id:
            sign_headers["X-Request-Id"] = request_id
        if include_session and self.session_id:
            sign_headers["mcp-session-id"] = self.session_id

        aws_request = AWSRequest(
            method="POST",
            url=self.url,
            headers=sign_headers,
            data=payload,
        )
        SigV4Auth(self._credentials, "bedrock-agentcore", self.region).add_auth(
            aws_request
        )

        return requests.post(
            self.url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": accept,
                **({"X-Request-Id": request_id} if request_id else {}),
                "X-Amz-Date": aws_request.headers["X-Amz-Date"],
                "Authorization": aws_request.headers["Authorization"],
                **(
                    {
                        "X-Amz-Security-Token": aws_request.headers[
                            "X-Amz-Security-Token"
                        ]
                    }
                    if "X-Amz-Security-Token" in aws_request.headers
                    else {}
                ),
                **(
                    {"mcp-session-id": self.session_id}
                    if include_session and self.session_id
                    else {}
                ),
            },
        )

    def _stream_signed_request(
        self,
        payload: str,
        accept: str,
        *,
        include_session: bool = True,
        request_id: Optional[str] = None,
    ):
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest

        sign_headers = {
            "Content-Type": "application/json",
            "Accept": accept,
        }
        if request_id:
            sign_headers["X-Request-Id"] = request_id
        if include_session and self.session_id:
            sign_headers["mcp-session-id"] = self.session_id

        aws_request = AWSRequest(
            method="POST",
            url=self.url,
            headers=sign_headers,
            data=payload,
        )
        SigV4Auth(self._credentials, "bedrock-agentcore", self.region).add_auth(
            aws_request
        )

        return httpx.stream(
            "POST",
            self.url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": accept,
                **({"X-Request-Id": request_id} if request_id else {}),
                "X-Amz-Date": aws_request.headers["X-Amz-Date"],
                "Authorization": aws_request.headers["Authorization"],
                **(
                    {
                        "X-Amz-Security-Token": aws_request.headers[
                            "X-Amz-Security-Token"
                        ]
                    }
                    if "X-Amz-Security-Token" in aws_request.headers
                    else {}
                ),
                **(
                    {"mcp-session-id": self.session_id}
                    if include_session and self.session_id
                    else {}
                ),
            },
        )

    def invoke(self, tool_name: str, args: dict, request_id: Optional[str] = None):
        """
        使用 SigV4 对请求进行签名。
        关键改动：支持session_id复用，避免每次请求都创建新session
        """
        self._request_id += 1
        rpc_id = request_id if request_id is not None else self._request_id
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": args},
                "id": rpc_id,
            }
        )

        transport = self.transport or "http-streamable"
        if transport == "sse":
            with self._stream_signed_request(
                payload,
                accept="text/event-stream, application/json",
                request_id=request_id,
            ) as response:
                response.raise_for_status()
                request_id = response.headers.get("x-amzn-RequestId")
                self.session_id = response.headers.get("Mcp-Session-Id")
                response_payload = self._read_streamable_response(response)
                self._raise_if_mcp_error(response_payload)
                _log_mcp_tool_error(
                    response_payload,
                    client_name=self.__class__.__name__,
                    tool_name=tool_name,
                )
                return request_id

        response = self._post_signed_request(
            payload,
            accept="application/json, text/event-stream",
            request_id=request_id,
        )
        response.raise_for_status()

        # 从响应头获取 request_id 和 session_id
        request_id = response.headers.get("x-amzn-RequestId")
        # 如果响应中有session_id，保存它以便后续请求复用
        self.session_id = response.headers.get("Mcp-Session-Id")

        response_payload = self._read_response_payload(response)
        self._raise_if_mcp_error(response_payload)
        _log_mcp_tool_error(
            response_payload,
            client_name=self.__class__.__name__,
            tool_name=tool_name,
        )

        return request_id


class AWSAgentCoreMCPDeployer:
    """AWS AgentCore MCP 服务部署"""

    def __init__(self, bench_name: str):
        self.bench_name = bench_name
        from atsuite.aws.aws import AWS

        self.aws = AWS()

    def deploy_target(
        self, target_name: str, runtime_config: RuntimeConfig
    ) -> Optional[str]:
        service_name = normalize_node_name(target_name)
        print(f"[MCP] Using AgentCore mode for '{service_name}'")
        tag = f"atsuite-mcp-{self.bench_name.lower()}-{service_name.lower()}"

        agentcore = self.aws.deploy_agentcore(
            node_name=service_name,
            tag=tag,
            cpu=runtime_config.cpu,
            memory=runtime_config.memory,
            timeout=runtime_config.timeout,
        )
        return agentcore.deploy()

    def deploy_node(self, service_name: str, config) -> Optional[str]:
        runtime_config = RuntimeConfig(
            cpu=config["config"]["cpu"],
            memory=config["config"]["memory"],
            timeout=config["config"]["timeout"],
            disk=config["config"].get("disk", 512),
        )
        return self.deploy_target(service_name, runtime_config)


class AliMCPDeployer:
    def __init__(self, bench_name: str):
        # Lazy import to avoid requiring Alibaba SDK for non-Ali providers.
        from atsuite.ali.ali import Ali

        self.bench_name = bench_name
        self.ali = Ali()

    def deploy_target(
        self, target_name: str, runtime_config: RuntimeConfig
    ) -> Optional[str]:
        service_name = normalize_node_name(target_name)
        tag = f"atsuite-mcp-{self.bench_name.lower()}-{service_name.lower()}"
        fn = self.ali.deploy_mcp(
            function_name=service_name,
            entrypoint=["python", "-m", "atsuite_sdk.mcp_server"],
            tag=tag,
            runtime="custom-container",
            cpu=runtime_config.cpu,
            memory_size=runtime_config.memory,
            disk_size=runtime_config.disk,
            timeout=runtime_config.timeout,
        )
        return fn.deploy()

    def deploy_node(self, service_name: str, config) -> Optional[str]:
        runtime_config = RuntimeConfig(
            cpu=config["config"]["cpu"],
            memory=config["config"]["memory"],
            disk=config["config"]["disk"],
            timeout=config["config"]["timeout"],
        )
        return self.deploy_target(service_name, runtime_config)


class GCPMCPDeployer:
    def __init__(self, bench_name: str):
        from atsuite.gcp.gcp import GCP

        self.bench_name = bench_name
        self.gcp = GCP()

    def deploy_target(
        self, target_name: str, runtime_config: RuntimeConfig
    ) -> Optional[str]:
        service_name = normalize_node_name(target_name)
        tag = f"atsuite-mcp-{self.bench_name.lower()}-{service_name.lower()}"
        fn = self.gcp.deploy_mcp(
            function_name=service_name,
            entrypoint=["python", "-m", "atsuite_sdk.mcp_server"],
            tag=tag,
            runtime="custom-container",
            cpu=runtime_config.cpu,
            memory_size=runtime_config.memory,
            disk_size=runtime_config.disk,
            timeout=runtime_config.timeout,
        )
        return fn.deploy()

    def deploy_node(self, service_name: str, config) -> Optional[str]:
        runtime_config = RuntimeConfig(
            cpu=config["config"]["cpu"],
            memory=config["config"]["memory"],
            disk=config["config"]["disk"],
            timeout=config["config"]["timeout"],
        )
        return self.deploy_target(service_name, runtime_config)


if __name__ == "__main__":
    client = AgentCoreMCPClient(
        "https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/arn%3Aaws%3Abedrock-agentcore%3Aus-east-1%3A843479649058%3Aruntime%2Fatsuite_travelplanner-AStSB0BNLc/invocations?qualifier=DEFAULT"
    )
    client.initialize()
    print(
        client.invoke(
            "flights_run",
            {
                "origin": "Sarasota",
                "destination": "Chicago",
                "departure_date": "2022-03-23",
            },
        )
    )
