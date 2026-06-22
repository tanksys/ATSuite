# GCP Cloud Storage：部署用 ensure_bucket；invoker 清理用 deleteobj

import os
from typing import Optional

from google.cloud import storage as gcs_storage
from google.cloud.exceptions import NotFound


def _get_project() -> str:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        raise RuntimeError(
            "not set GCP project, please execute: export GOOGLE_CLOUD_PROJECT=your projcet ID"
        )
    return project


class GCPStorage:
    # GCP Cloud Storage: ensure_bucket, upload_zip (for deployment), deleteobj (for cleaner)

    def __init__(
        self,
        project_id: Optional[str] = None,
        region: str = "us-central1",
        client: Optional[gcs_storage.Client] = None,
    ):
        self._project_id = project_id or _get_project()
        self._region = region
        self._client = client or gcs_storage.Client(project=self._project_id)

    def ensure_bucket(self, bucket_name: str) -> str:
        # if bucket exists, return, otherwise create it and return bucket name
        try:
            self._client.get_bucket(bucket_name)
            return bucket_name
        except NotFound:
            bucket = self._client.create_bucket(bucket_name, location=self._region)
            return bucket.name

    def upload_zip(
        self, bucket_name: str, object_key: str, local_zip_path: str
    ) -> str:
        # upload zip to GCS and return gs:// URL
        bucket = self._client.bucket(bucket_name)
        blob = bucket.blob(object_key)
        blob.upload_from_filename(local_zip_path, content_type="application/zip")
        return f"gs://{bucket_name}/{object_key}"

    def getobjsize(self, bucket_name: str, key: str) -> float:
        # return object size in GB
        bucket = self._client.bucket(bucket_name)
        blob = bucket.get_blob(key)
        if blob is None or blob.size is None:
            return 0.0
        return float(blob.size) / (1024**3)

    def deleteobj(self, bucket_name: str, key: str) -> None:
        # delete object, used for invoker_utils.cleaner
        try:
            bucket = self._client.bucket(bucket_name)
            blob = bucket.blob(key)
            blob.delete()
        except NotFound:
            pass
