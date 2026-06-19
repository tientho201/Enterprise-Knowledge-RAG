"""
AWS S3 storage client — compatible với LocalStack (local dev) và AWS S3 thật (production).

Local dev:  LocalStack tại http://localhost:4566
Production: AWS S3 (để trống AWS_S3_ENDPOINT_URL)
"""
import io
from functools import lru_cache
from typing import BinaryIO

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import settings


class S3Client:
    def __init__(self):
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

    def _ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            if error_code in ("404", "NoSuchBucket"):
                if settings.AWS_REGION == "us-east-1":
                    self.client.create_bucket(Bucket=self.bucket)
                else:
                    self.client.create_bucket(
                        Bucket=self.bucket,
                        CreateBucketConfiguration={"LocationConstraint": settings.AWS_REGION},
                    )
            else:
                raise

    def upload_file(
        self,
        object_name: str,
        data: BinaryIO,
        size: int,  # noqa: ARG002 — kept for interface compat with previous MinIO client
        content_type: str = "application/octet-stream",
    ) -> str:
        self.client.upload_fileobj(
            data,
            self.bucket,
            object_name,
            ExtraArgs={"ContentType": content_type},
        )
        return object_name

    def upload_bytes(
        self,
        object_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        self.client.put_object(
            Bucket=self.bucket,
            Key=object_name,
            Body=data,
            ContentType=content_type,
        )
        return object_name

    def download_file(self, object_name: str) -> bytes:
        buffer = io.BytesIO()
        self.client.download_fileobj(self.bucket, object_name, buffer)
        return buffer.getvalue()

    def delete_file(self, object_name: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=object_name)

    def get_presigned_url(self, object_name: str, expires_seconds: int = 3600) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": object_name},
            ExpiresIn=expires_seconds,
        )

    def file_exists(self, object_name: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=object_name)
            return True
        except ClientError:
            return False


@lru_cache
def get_s3_client() -> S3Client:
    return S3Client()
