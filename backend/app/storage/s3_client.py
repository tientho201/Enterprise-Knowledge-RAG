"""
AWS S3 storage client — document raw file storage.

Responsibility:
  - Upload/download/delete raw document files (PDF, DOCX, TXT)
  - Generate presigned URLs for direct download
  - All metadata (document records, chunks, audit logs) stays in Supabase/PostgreSQL

Local dev:  LocalStack tại http://localhost:4566
            AWS_S3_ENDPOINT_URL=http://localhost:4566
            AWS_ACCESS_KEY_ID=test / AWS_SECRET_ACCESS_KEY=test
Production: AWS S3 thật — để trống AWS_S3_ENDPOINT_URL
"""

import asyncio
import io
import logging
from functools import lru_cache
from typing import BinaryIO

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)


class S3Client:
    """
    Sync S3 client (boto3).

    Dùng trong:
    - Celery tasks (sync context) → gọi trực tiếp
    - FastAPI async endpoints     → wrap bằng run_in_executor (xem async helpers bên dưới)
    """

    def __init__(self) -> None:
        kwargs: dict = {
            "aws_access_key_id": settings.AWS_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.AWS_SECRET_ACCESS_KEY,
            "region_name": settings.AWS_REGION,
            "config": Config(signature_version="s3v4"),
        }
        if settings.AWS_S3_ENDPOINT_URL:
            kwargs["endpoint_url"] = settings.AWS_S3_ENDPOINT_URL

        self.client = boto3.client("s3", **kwargs)
        self.bucket = settings.AWS_S3_BUCKET_NAME
        self._ensure_bucket()

    # ── Bucket bootstrap ──────────────────────────────────────────────────────

    def _ensure_bucket(self) -> None:
        """Create bucket if it does not exist (idempotent)."""
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("404", "NoSuchBucket"):
                try:
                    if settings.AWS_REGION == "us-east-1":
                        self.client.create_bucket(Bucket=self.bucket)
                    else:
                        self.client.create_bucket(
                            Bucket=self.bucket,
                            CreateBucketConfiguration={"LocationConstraint": settings.AWS_REGION},
                        )
                    logger.info("Created S3 bucket: %s", self.bucket)
                except ClientError as create_exc:
                    logger.error("Failed to create S3 bucket %s: %s", self.bucket, create_exc)
                    raise
            else:
                raise

    # ── Write ─────────────────────────────────────────────────────────────────

    def upload_file(
        self,
        object_name: str,
        data: BinaryIO,
        size: int,  # noqa: ARG002 — kept for interface compat
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload a file-like object. Returns object_name."""
        self.client.upload_fileobj(
            data,
            self.bucket,
            object_name,
            ExtraArgs={"ContentType": content_type},
        )
        logger.debug("S3 upload_file: s3://%s/%s", self.bucket, object_name)
        return object_name

    def upload_bytes(
        self,
        object_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload raw bytes. Returns object_name."""
        self.client.put_object(
            Bucket=self.bucket,
            Key=object_name,
            Body=data,
            ContentType=content_type,
        )
        logger.debug("S3 upload_bytes: s3://%s/%s (%d bytes)", self.bucket, object_name, len(data))
        return object_name

    # ── Read ──────────────────────────────────────────────────────────────────

    def download_file(self, object_name: str) -> bytes:
        """Download raw bytes from S3."""
        buffer = io.BytesIO()
        self.client.download_fileobj(self.bucket, object_name, buffer)
        return buffer.getvalue()

    def get_presigned_url(self, object_name: str, expires_seconds: int = 3600) -> str:
        """Generate a time-limited presigned URL for direct download."""
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": object_name},
            ExpiresIn=expires_seconds,
        )

    def file_exists(self, object_name: str) -> bool:
        """Return True if the object exists in S3."""
        try:
            self.client.head_object(Bucket=self.bucket, Key=object_name)
            return True
        except ClientError:
            return False

    # ── Delete ────────────────────────────────────────────────────────────────

    def delete_file(self, object_name: str) -> None:
        """Delete a single object from S3."""
        self.client.delete_object(Bucket=self.bucket, Key=object_name)
        logger.debug("S3 delete: s3://%s/%s", self.bucket, object_name)

    def delete_files(self, object_names: list[str]) -> None:
        """Batch delete up to 1000 objects in one API call."""
        if not object_names:
            return
        objects = [{"Key": k} for k in object_names]
        self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": objects})
        logger.debug("S3 batch_delete: %d objects from bucket %s", len(objects), self.bucket)


# ── Singleton ─────────────────────────────────────────────────────────────────


@lru_cache
def get_s3_client() -> S3Client:
    return S3Client()


# ── Async helpers (for use in FastAPI async endpoints) ────────────────────────
# boto3 is sync-only. Running it directly in an async endpoint blocks the event loop.
# These wrappers use run_in_executor so the upload/download runs in a thread pool.


async def upload_bytes_async(
    object_name: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> str:
    """Non-blocking upload for use inside async FastAPI route handlers."""
    loop = asyncio.get_running_loop()
    s3 = get_s3_client()
    return await loop.run_in_executor(
        None, lambda: s3.upload_bytes(object_name, data, content_type)
    )


async def download_file_async(object_name: str) -> bytes:
    """Non-blocking download for use inside async FastAPI route handlers."""
    loop = asyncio.get_running_loop()
    s3 = get_s3_client()
    return await loop.run_in_executor(None, lambda: s3.download_file(object_name))


async def delete_file_async(object_name: str) -> None:
    """Non-blocking delete for use inside async FastAPI route handlers."""
    loop = asyncio.get_running_loop()
    s3 = get_s3_client()
    await loop.run_in_executor(None, lambda: s3.delete_file(object_name))


async def get_presigned_url_async(object_name: str, expires_seconds: int = 3600) -> str:
    """Non-blocking presigned URL generation."""
    loop = asyncio.get_running_loop()
    s3 = get_s3_client()
    return await loop.run_in_executor(
        None, lambda: s3.get_presigned_url(object_name, expires_seconds)
    )
