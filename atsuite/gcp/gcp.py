# GCP 入口：project/region、Storage、Cloud Run 部署（镜像 push + gcloud run deploy）

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()
_root = Path(__file__).resolve().parents[2]
load_dotenv(_root / ".env")

from atsuite.gcp.fc import GCPFC
from atsuite.gcp.storage import GCPStorage


def _get_project() -> str:
    p = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not p:
        raise RuntimeError("not set GOOGLE_CLOUD_PROJECT")
    return p


def _get_region() -> str:
    return os.environ.get("GCP_REGION", "us-central1")


class GCP:
    def __init__(
        self,
        project_id: Optional[str] = None,
        region: Optional[str] = None,
    ):
        self._project_id = project_id or _get_project()
        self._region = region or _get_region()
        self._storage: Optional[GCPStorage] = None

    def get_storage_client(self) -> GCPStorage:
        if self._storage is None:
            self._storage = GCPStorage(
                project_id=self._project_id,
                region=self._region,
            )
        return self._storage

    def deploy_function(self, **kwargs) -> GCPFC:
        return GCPFC(
            project_id=self._project_id,
            region=self._region,
            typ="function",
            **kwargs,
        )

    def deploy_mcp(self, **kwargs) -> GCPFC:
        return GCPFC(
            project_id=self._project_id,
            region=self._region,
            typ="mcp",
            **kwargs,
        )
