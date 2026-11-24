"""Private object storage (Amazon S3, Cloudflare R2, MinIO) for verification documents and delivery proof, plus upload validation.

Rules:
* PRIVATE: the bucket must not be public. Files are never served by this app; a reader gets a SHORT-LIVED SIGNED URL (S3_SIGNED_URL_SECONDS,
  30-900 s) that forces a download (`attachment`), so an uploaded file is never rendered inline in our origin.
* The server trusts nothing from the client: the object key is random (never the file name), the content type is decided from the file's
  own first bytes and must equal what the client declared, only PDF/JPEG/PNG/WebP are accepted, size is capped (UPLOAD_MAX_MB), and PDFs
  carrying active content (JavaScript, launch actions, embedded files) are refused. This is NOT malware scanning: run an AV scan
  (for example ClamAV) on the bucket in production, and have staff open documents on a managed device.
* Uploaded does NOT mean verified: an administrator reviews each document (stored_documents.review_status).
Configuration (environment only): S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY, optional S3_ENDPOINT (R2/MinIO), S3_REGION, S3_SIGNED_URL_SECONDS.
LIVE USE IS UNTESTED here (no bucket); tests use an in-memory storage.
"""
from __future__ import annotations

import re
import uuid
from typing import Mapping, Optional

MAGIC = (("application/pdf", b"%PDF-"), ("image/jpeg", b"\xff\xd8\xff"), ("image/png", b"\x89PNG\r\n\x1a\n"))
EXT = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
ACTIVE_PDF = (b"/JavaScript", b"/JS", b"/Launch", b"/EmbeddedFile", b"/OpenAction", b"/RichMedia", b"/XFA")
KINDS = {
    "organization": {"registration_certificate", "darpan", "jj_act_registration", "cert_12a", "cert_80g", "supporting"},
    "volunteer": {"id_document", "police_verification", "code_of_conduct", "supporting"},
    "delivery": {"delivery_proof"},
}


class UploadError(ValueError):
    pass


class StorageUnavailable(RuntimeError):
    pass


def max_bytes(env: Mapping[str, str]) -> int:
    try:
        mb = float(env.get("UPLOAD_MAX_MB") or 5)
    except ValueError:
        mb = 5
    return int(max(0.1, min(20, mb)) * 1024 * 1024)


def signed_url_seconds(env: Mapping[str, str]) -> int:
    try:
        return max(30, min(900, int(env.get("S3_SIGNED_URL_SECONDS") or 300)))
    except ValueError:
        return 300


def sniff(data: bytes) -> Optional[str]:
    """The real type of a file from its first bytes (never from its name or the client's claim)."""
    for ctype, magic in MAGIC:
        if data.startswith(magic):
            return ctype
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def safe_filename(name: object) -> str:
    base = re.split(r"[\\/]", str(name or ""))[-1]
    base = re.sub(r"[^A-Za-z0-9._ \-]", "", base).strip(" .")
    return (base or "document")[:100]


def validate_upload(filename: object, declared_type: object, data: bytes, limit: int) -> tuple[str, str]:
    """(content_type, safe_filename) or UploadError with a message safe to show the person."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise UploadError("The file is empty.")
    if len(data) > limit:
        raise UploadError(f"The file is too large (the limit is {limit // (1024 * 1024)} MB).")
    detected = sniff(bytes(data))
    if detected is None:
        raise UploadError("Only PDF, JPEG, PNG or WebP files can be uploaded.")
    if str(declared_type or "").lower().split(";")[0].strip() != detected:
        raise UploadError("The file does not match its declared type.")
    if detected == "application/pdf" and any(marker in data for marker in ACTIVE_PDF):
        raise UploadError("This PDF contains active content (scripts or embedded files). Please upload a plain scan or print-to-PDF.")
    return detected, safe_filename(filename)


def object_key(owner_type: str, owner_id: int, kind: str, content_type: str) -> str:
    return f"{owner_type}/{int(owner_id)}/{kind}/{uuid.uuid4().hex}{EXT[content_type]}"


class MemoryStorage:
    """For tests only."""

    def __init__(self):
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.deleted: list[str] = []

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (bytes(data), content_type)

    def signed_url(self, key: str, seconds: int, filename: str) -> str:
        if key not in self.objects:
            raise StorageUnavailable("missing")
        return f"https://storage.test/{key}?expires={seconds}&filename={filename}"

    def delete(self, key: str) -> None:
        self.objects.pop(key, None); self.deleted.append(key)


class S3Storage:
    def __init__(self, env: Mapping[str, str], client=None):
        self.bucket = env["S3_BUCKET"].strip()
        self.default_seconds = signed_url_seconds(env)
        if client is None:
            import boto3
            from botocore.config import Config
            endpoint = (env.get("S3_ENDPOINT") or "").strip() or None
            client = boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=env["S3_ACCESS_KEY"].strip(), aws_secret_access_key=env["S3_SECRET_KEY"].strip(),
                                  region_name=(env.get("S3_REGION") or "auto").strip(), config=Config(signature_version="s3v4", s3={"addressing_style": "path" if endpoint else "auto"}))
        self.client = client

    def __repr__(self) -> str:
        return "S3Storage(configured)"                                 # never expose credentials

    def put(self, key: str, data: bytes, content_type: str) -> None:
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=bytes(data), ContentType=content_type, ContentDisposition="attachment")
        except Exception as exc:
            raise StorageUnavailable(type(exc).__name__) from None

    def signed_url(self, key: str, seconds: int, filename: str) -> str:
        try:
            return self.client.generate_presigned_url("get_object", ExpiresIn=max(30, min(900, int(seconds))),
                                                      Params={"Bucket": self.bucket, "Key": key, "ResponseContentDisposition": f'attachment; filename="{safe_filename(filename)}"'})
        except Exception as exc:
            raise StorageUnavailable(type(exc).__name__) from None

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            raise StorageUnavailable(type(exc).__name__) from None


def configured(env: Mapping[str, str]) -> bool:
    return all((env.get(k) or "").strip() for k in ("S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY"))


def get_storage(env: Mapping[str, str]):
    """The configured storage, or None. (boto3 is imported only when a bucket is configured.)"""
    if not configured(env):
        return None
    try:
        return S3Storage(env)
    except Exception as exc:
        raise StorageUnavailable(type(exc).__name__) from None
