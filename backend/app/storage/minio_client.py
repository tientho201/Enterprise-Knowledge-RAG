import io
from functools import lru_cache
from typing import BinaryIO

from minio import Minio
from minio.error import S3Error

from app.core.config import settings


class MinIOClient:
    def __init__(self):
        self.client = Minio(
            endpoint=settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        self.bucket = settings.MINIO_BUCKET_NAME
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def upload_file(
        self,
        object_name: str,
        data: BinaryIO,
        size: int,
        content_type: str = "application/octet-stream",
    ) -> str:
        self.client.put_object(
            bucket_name=self.bucket,
            object_name=object_name,
            data=data,
            length=size,
            content_type=content_type,
        )
        return object_name

    def upload_bytes(
        self,
        object_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        self.client.put_object(
            bucket_name=self.bucket,
            object_name=object_name,
            data=io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        return object_name

    def download_file(self, object_name: str) -> bytes:
        response = self.client.get_object(self.bucket, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def delete_file(self, object_name: str) -> None:
        self.client.remove_object(self.bucket, object_name)

    def get_presigned_url(self, object_name: str, expires_seconds: int = 3600) -> str:
        from datetime import timedelta
        return self.client.presigned_get_object(
            self.bucket, object_name, expires=timedelta(seconds=expires_seconds)
        )

    def file_exists(self, object_name: str) -> bool:
        try:
            self.client.stat_object(self.bucket, object_name)
            return True
        except S3Error:
            return False


@lru_cache
def get_minio_client() -> MinIOClient:
    return MinIOClient()
