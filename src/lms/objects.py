"""Object storage for statement artifacts and brand assets.

The statement body is the payload the statement issuer already produced.
This module does not render a new PDF and does not change a calculation.
"""

from __future__ import annotations


class ObjectStoreError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class MemoryStore:
    """In-process stand-in used by tests. It does not talk to AWS."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[str, bytes]] = {}

    def check(self) -> None:
        return None

    def put(self, key: str, body: bytes, content_type: str) -> str:
        if not key or key.startswith("/") or ".." in key.split("/"):
            raise ObjectStoreError("object-key", "The object key is not usable.")
        self.objects[key] = (content_type, body)
        return key


class S3Store:
    """Put objects into one private bucket. A missing bucket fails closed."""

    def __init__(self, bucket: str, client=None) -> None:
        if not bucket or not bucket.strip():
            raise ObjectStoreError("object-store-unset", "LMS_S3_BUCKET is missing.")
        self.bucket = bucket.strip()
        self._client = client

    def client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("s3")
        return self._client

    def check(self) -> None:
        try:
            self.client().head_bucket(Bucket=self.bucket)
        except Exception as exc:
            raise ObjectStoreError(
                "object-store-unset",
                f"The statement bucket {self.bucket} is not reachable. {exc}",
            ) from exc

    def put(self, key: str, body: bytes, content_type: str) -> str:
        if not key or key.startswith("/") or ".." in key.split("/"):
            raise ObjectStoreError("object-key", "The object key is not usable.")
        try:
            self.client().put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
            )
        except Exception as exc:
            raise ObjectStoreError(
                "object-store-refused",
                f"The statement bucket refused the object. {exc}",
            ) from exc
        return key
