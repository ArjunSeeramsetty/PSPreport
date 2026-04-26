from __future__ import annotations

from pathlib import Path

from minio import Minio


class MinioRawStore:
    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool,
    ):
        self.client = Minio(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

    def ensure_bucket(self, bucket_name: str) -> None:
        if not self.client.bucket_exists(bucket_name):
            self.client.make_bucket(bucket_name)

    def upload_file(self, *, bucket_name: str, object_name: str, local_path: str) -> str:
        path = Path(local_path)
        self.client.fput_object(bucket_name, object_name, str(path))
        return object_name

