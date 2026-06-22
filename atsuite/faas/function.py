import json
import os
import requests

from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from atsuite.pipeline import RuntimeConfig
from atsuite.utils import normalize_node_name
from atsuite.faas.config import function_config_path, load_function_config

try:
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    from botocore.session import Session as BotocoreSession
except ImportError:  # pragma: no cover - exercised only when aws extras are absent
    SigV4Auth = None
    AWSRequest = None
    BotocoreSession = None


class FunctionClient:
    def __init__(self, url: str):
        self.url = url.rstrip("/")
        self._aws_credentials = None
        self.timeout = 1800

        # Use a plain session: no client-side timeout and no automatic retries.
        self.session = requests.Session()

    def invoke(self, tool_name: str, args: dict, request_id: Optional[str] = None):
        tool_name_safe = tool_name.replace(".", "_")
        payload = {
            "tool": tool_name_safe,
            "args": args,
        }

        invoke_url = f"{self.url}/run"
        if self._is_aws_lambda_function_url():
            body = json.dumps(payload)
            headers = self._build_aws_lambda_sigv4_headers(
                invoke_url,
                body,
                request_id=request_id,
            )
            response = self.session.post(
                invoke_url,
                data=body,
                headers=headers,
            )
        else:
            headers = {}
            if request_id:
                headers["X-Request-Id"] = request_id
            response = self.session.post(
                invoke_url,
                json=payload,
                headers=headers or None,
            )

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as err:
            raise RuntimeError(
                self._format_response_error(
                    response,
                    invoke_url,
                    prefix=f"Function invoke failed with HTTP {response.status_code}",
                )
            ) from err

        try:
            rsp = response.json()
        except requests.exceptions.JSONDecodeError as err:
            raise RuntimeError(
                self._format_response_error(
                    response,
                    invoke_url,
                    prefix="Function invoke returned non-JSON response",
                )
            ) from err

        result = rsp.get("result")
        if isinstance(result, str):
            stripped = result.strip()
            if stripped and stripped[0] in "[{":
                try:
                    result = json.loads(stripped)
                except json.JSONDecodeError:
                    pass
        if isinstance(result, dict) and result.get("isError"):
            print(result)

        # Ali Cloud: X-Fc-Request-Id
        # AWS Lambda: x-amzn-requestid
        request_id = (
            response.headers.get("X-Fc-Request-Id")
            or response.headers.get("x-amzn-requestid")
            or request_id
        )

        is_stateful = response.headers.get("X-Tool-Stateful", "false").lower() == "true"

        return request_id, is_stateful

    @staticmethod
    def _format_response_error(
        response: requests.Response,
        invoke_url: str,
        *,
        prefix: str,
    ) -> str:
        content_type = response.headers.get("Content-Type", "").strip() or "unknown"
        preview = " ".join(response.text.strip().split())
        if len(preview) > 240:
            preview = preview[:237] + "..."
        return (
            f"{prefix} from {invoke_url} "
            f"(content-type: {content_type}): {preview or '<empty body>'}"
        )

    # class FunctionClient:
    #     def __init__(self, url: str):
    #         self.url = url.rstrip("/")

    #     def invoke(self, tool_name: str, args: dict, request_id: Optional[str] = None):
    #         tool_name_safe = tool_name.replace(".", "_")
    #         headers = {}
    #         if request_id:
    #             headers["X-Request-Id"] = request_id
    #         response = requests.post(
    #             f"{self.url}/run",
    #             json={
    #                 "tool": tool_name_safe,
    #                 "args": args,
    #             },
    #             headers=headers or None,
    #         )
    #         response.raise_for_status()
    #         # Ali Cloud: X-Fc-Request-Id, AWS Lambda: x-amzn-requestid
    #         request_id = response.headers.get("X-Fc-Request-Id") or response.headers.get("x-amzn-requestid") or request_id
    #         is_stateful = response.headers.get("X-Tool-Stateful", "false").lower() == "true"
    #         return request_id, is_stateful
    #         # return response.json()

    def _is_aws_lambda_function_url(self) -> bool:
        host = urlparse(self.url).netloc.lower()
        return ".lambda-url." in host and host.endswith(".on.aws")

    def _lambda_region(self) -> str:
        host = urlparse(self.url).netloc.lower()
        marker = ".lambda-url."
        suffix = ".on.aws"
        if marker in host and host.endswith(suffix):
            start = host.index(marker) + len(marker)
            end = host.rfind(suffix)
            region = host[start:end]
            if region:
                return region
        return os.environ.get("AWS_REGION", "us-east-1")

    def _get_aws_credentials(self):
        if self._aws_credentials is None:
            if BotocoreSession is None:
                raise RuntimeError(
                    "botocore is required for AWS Lambda Function URL IAM auth"
                )
            credentials = BotocoreSession().get_credentials()
            if credentials is None:
                raise RuntimeError(
                    "AWS credentials are required for Lambda Function URL IAM auth"
                )
            self._aws_credentials = credentials.get_frozen_credentials()
        return self._aws_credentials

    def _build_aws_lambda_sigv4_headers(
        self,
        invoke_url: str,
        body: str,
        *,
        request_id: Optional[str] = None,
    ) -> dict:
        if SigV4Auth is None or AWSRequest is None:
            raise RuntimeError(
                "botocore is required for AWS Lambda Function URL IAM auth"
            )

        headers = {"Content-Type": "application/json"}
        if request_id:
            headers["X-Request-Id"] = request_id

        aws_request = AWSRequest(
            method="POST",
            url=invoke_url,
            headers=headers,
            data=body,
        )
        SigV4Auth(
            self._get_aws_credentials(),
            "lambda",
            self._lambda_region(),
        ).add_auth(aws_request)
        return dict(aws_request.headers.items())


class AliFunctionDeployer:
    def __init__(self, bench_name: str):
        from atsuite.ali.ali import Ali

        self.bench_name = bench_name
        self.ali = Ali()

    def deploy_target(
        self, target_name: str, runtime_config: RuntimeConfig
    ) -> Optional[str]:
        node_name = normalize_node_name(target_name)
        tag = f"atsuite-function-{self.bench_name.lower()}-{node_name.lower()}"
        fn = self.ali.deploy_function(
            function_name=node_name,
            entrypoint=["python", "-m", "atsuite_sdk.function"],
            tag=tag,
            runtime="custom-container",
            cpu=runtime_config.cpu,
            memory_size=runtime_config.memory,
            disk_size=runtime_config.disk,
            timeout=runtime_config.timeout,
        )
        return fn.deploy()

    def deploy_node(self, node_name: str, node_dir: Path) -> Optional[str]:
        config_path = function_config_path(node_dir)
        fun_config = load_function_config(config_path)
        return self.deploy_target(node_name, fun_config)


class GCPFunctionDeployer:
    def __init__(self, bench_name: str):
        from atsuite.gcp.gcp import GCP

        self.bench_name = bench_name
        self.gcp = GCP()

    def deploy_target(
        self, target_name: str, runtime_config: RuntimeConfig
    ) -> Optional[str]:
        node_name = normalize_node_name(target_name)
        tag = f"atsuite-function-{self.bench_name.lower()}-{node_name.lower()}"
        fn = self.gcp.deploy_function(
            function_name=node_name,
            entrypoint=["python", "-m", "atsuite_sdk.function"],
            tag=tag,
            runtime="custom-container",
            cpu=runtime_config.cpu,
            memory_size=runtime_config.memory,
            disk_size=runtime_config.disk,
            timeout=runtime_config.timeout,
        )
        return fn.deploy()

    def deploy_node(self, node_name: str, node_dir: Path) -> Optional[str]:
        config_path = function_config_path(node_dir)
        fun_config = load_function_config(config_path)
        return self.deploy_target(node_name, fun_config)


class AWSFunctionDeployer:
    def __init__(self, bench_name: str):
        self.bench_name = bench_name
        from atsuite.aws.aws import AWS

        self.aws = AWS()

    def deploy_target(
        self, target_name: str, runtime_config: RuntimeConfig
    ) -> Optional[str]:
        node_name = normalize_node_name(target_name)
        tag = f"atsuite-function-{self.bench_name.lower()}-{node_name.lower()}"

        fn = self.aws.deploy_lambda(
            function_name=node_name,
            entrypoint=["python", "-m", "atsuite_sdk.function"],
            tag=tag,
            runtime="custom-container",
            cpu=runtime_config.cpu,
            memory_size=runtime_config.memory,
            timeout=runtime_config.timeout,
            disk_size=runtime_config.disk,
        )
        return fn.deploy()

    def deploy_node(self, node_name: str, node_dir: Path) -> Optional[str]:
        config_path = function_config_path(node_dir)
        runtime_config = load_function_config(config_path)
        return self.deploy_target(node_name, runtime_config)
