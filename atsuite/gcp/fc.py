# GCP Cloud Run 部署：镜像推送到 Artifact Registry / GCR，gcloud run deploy 返回 URL

import os
import subprocess
from typing import Any, Optional

from atsuite.function import FunctionBase
from atsuite.utils import run


_CLOUD_RUN_MAX_TIMEOUT_SECONDS = 3600


def _get_project() -> str:
    p = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not p:
        raise RuntimeError("not set GOOGLE_CLOUD_PROJECT")
    return p


def _get_region() -> str:
    return os.environ.get("GCP_REGION", "us-central1")


def _cloud_run_service_name(name: str) -> str:
    # normalize service name, gcloud run service name only allows lowercase letters, numbers and -
    return name.replace("_", "-").lower()


def _image_uri(project_id: str, tag: str) -> str:
    """镜像完整 URI。优先 GCP_IMAGE_PREFIX（如 us-central1-docker.pkg.dev/PROJECT/repo），否则 gcr.io/PROJECT。"""
    # image uri, prefer GCP_IMAGE_PREFIX (like us-central1-docker.pkg.dev/PROJECT/repo)
    prefix = os.environ.get("GCP_IMAGE_PREFIX")
    if prefix:
        return f"{prefix.rstrip('/')}/{tag}:latest"
    return f"gcr.io/{project_id}/{tag}:latest"


class GCPFC(FunctionBase):
    """Cloud Run 部署：本地镜像 tag → push → gcloud run deploy，返回服务 URL。"""
    # deploy function or mcp on GCP Cloud Run
    def __init__(
        self,
        function_name: str,
        entrypoint: list,
        tag: str,
        project_id: str,
        region: str,
        typ: str = "function",
        cpu: int = 1,
        memory_size: int = 1024,
        timeout: int = 60,
        session_affinity: Optional[bool] = None,
        min_instances: Optional[int] = None,
        **kwargs: Any,
    ):
        self.function_name = function_name
        self.entrypoint = entrypoint
        self.tag = tag
        self.project_id = project_id
        self.region = region
        self.typ = typ
        self.cpu = cpu
        self.memory_size = memory_size
        self.timeout = timeout
        self.session_affinity = session_affinity
        self.min_instances = min_instances

    def deploy(self) -> str:
        # tag local image to image uri and push to registry
        image_uri = _image_uri(self.project_id, self.tag)
        local_ref = f"{self.tag}:latest"

        # tag local image to image uri and push to registry
        run(["docker", "tag", local_ref, image_uri])
        run(["docker", "push", image_uri])

        # deploy function or mcp on GCP Cloud Run
        service_name = _cloud_run_service_name(self.function_name)
        port_env = "8080"  # cloud run use PORT=8080
        base = f"FC_SERVER_PORT={port_env}" if self.typ == "function" else f"ATSUITE_MCP_PORT={port_env}"
        gcp_storage_bucket = os.environ.get("GCP_BUCKET", os.environ.get("GOOGLE_CLOUD_PROJECT", self.project_id))
        env_vars = f"{base},PROVIDER=gcp,PROJECT={gcp_storage_bucket},GOOGLE_CLOUD_PROJECT={self.project_id}"
        # Cloud Run request timeout is currently capped at 3600 seconds.
        effective_timeout = _CLOUD_RUN_MAX_TIMEOUT_SECONDS
        deploy_cmd = [
            "gcloud", "run", "deploy", service_name,
            "--image", image_uri,
            "--region", self.region,
            "--platform", "managed",
            "--allow-unauthenticated",
            "--memory", f"{self.memory_size}Mi",
            "--cpu", str(self.cpu),
            "--concurrency", "50",
            "--timeout", str(effective_timeout),
            "--set-env-vars", env_vars,
        ]
        # Keep one warm instance for both function and MCP services on GCP.
        deploy_cmd.extend(
            ["--min-instances", str(self.min_instances if self.min_instances is not None else 1)]
        )
        # MCP services additionally require sticky sessions.
        if self.typ == "mcp":
            deploy_cmd.append("--session-affinity")
        run(deploy_cmd)

        url = self._get_service_url(service_name)  # service_name 已为 Cloud Run 合法名
        print("\n\nSuccess deploy on GCP Cloud Run\n\n")
        return url

    def _get_service_url(self, service_name: str) -> str:
        out = subprocess.run(
            [
                "gcloud", "run", "services", "describe", service_name,
                "--region", self.region,
                "--format", "value(status.url)",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip().rstrip("/")
