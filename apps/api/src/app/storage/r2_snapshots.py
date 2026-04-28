import asyncio
import logging

from app.config import settings

logger = logging.getLogger(__name__)


def _r2_bucket_name() -> str:
    bucket = settings.r2_bucket
    if not bucket or not bucket.strip():
        raise RuntimeError("R2 bucket is not configured")
    return bucket.strip()


def _r2_client() -> object:
    if not settings.has_r2_snapshot_archive_configured():
        raise RuntimeError("R2 snapshot archive is not configured")
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - dependency checked in runtime environments
        raise RuntimeError("boto3 is required for R2 snapshot archiving") from exc
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint_url,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name=settings.r2_region,
    )


async def upload_snapshot_to_r2(*, object_key: str, payload: bytes) -> None:
    def _upload() -> None:
        client = _r2_client()
        bucket = _r2_bucket_name()
        client.put_object(Bucket=bucket, Key=object_key, Body=payload)

    await asyncio.to_thread(_upload)


async def download_snapshot_from_r2(*, object_key: str) -> bytes | None:
    def _download() -> bytes | None:
        client = _r2_client()
        bucket = _r2_bucket_name()
        try:
            response = client.get_object(Bucket=bucket, Key=object_key)
        except Exception:
            logger.warning("Failed to load archived snapshot object_key=%s", object_key, exc_info=True)
            return None
        body = response.get("Body")
        if body is None:
            return None
        return body.read()

    return await asyncio.to_thread(_download)
