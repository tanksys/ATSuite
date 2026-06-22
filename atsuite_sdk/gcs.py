# GCP Cloud Storage 适配 StorageBase，供 Notebook 等节点在 Cloud Run 上使用

import os
from typing import Optional

from google.cloud import storage as gcs_storage
from google.cloud.exceptions import NotFound

from atsuite_sdk.storage import StorageBase


def _get_project() -> str:
    p = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not p:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT not set")
    return p


class GCPStorage(StorageBase):

    def __init__(
        self,
        bucket: str,
        project_id: Optional[str] = None,
        client: Optional[gcs_storage.Client] = None,
    ):
        self.bucket_name = bucket
        self._project_id = project_id or _get_project()
        self._client = client or gcs_storage.Client(project=self._project_id)
        self._bucket = self._client.bucket(self.bucket_name)

    def upload(self, key: str, filepath: str) -> None:
        blob = self._bucket.blob(key)
        blob.upload_from_filename(filepath)
        print(f"Upload {filepath} to {self.bucket_name}/{key}")

    def download(self, key: str, filepath: str) -> None:
        blob = self._bucket.blob(key)
        blob.download_to_filename(filepath)
        print(f"Download {self.bucket_name}/{key} to {filepath}")

    def append(self, key: str, data) -> int:
        blob = self._bucket.blob(key)
        try:
            existing = blob.download_as_bytes()
        except NotFound:
            existing = b""
        if isinstance(data, str):
            data = data.encode("utf-8")
        new_content = existing + data
        blob.upload_from_string(
            new_content,
            content_type="application/octet-stream",
        )
        return len(new_content)

    def read(self, key: str) -> str:
        try:
            blob = self._bucket.blob(key)
            return blob.download_as_text(encoding="utf-8")
        except NotFound:
            print("No such key")
            return ""

    def deleteobj(self, key: str) -> None:
        try:
            blob = self._bucket.blob(key)
            blob.delete()
        except NotFound:
            pass

    def clearobj(self, key: str) -> None:
        self.deleteobj(key)
