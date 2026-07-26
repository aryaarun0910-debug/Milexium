"""Content-addressed object storage over S3-compatible storage (MinIO in dev).

Program C's "immutable object and artifact objects" (blueprint 14/17) as a real
path, not just local disk. An object's key IS its sha256, so:

- storage is inherently deduplicated (same bytes -> same key);
- a read verifies the bytes hash back to the key (tamper/corruption-evident on
  every get, the same integrity stance as the event log's hash chain);
- keys are stable, portable references usable from a manifest.

This is the *object* backend; the estate catalog + manifests (app/estate/
acquire.py, catalog.py) remain the governance record and are unchanged. In dev
it points at the MinIO container from platform/infra/compose (ADR-0032). `minio` is an
optional dependency (the `objectstore` extra) imported lazily, so importing
this module or the estate package never requires it.

Credentials are read at runtime from platform/infra/compose/.env (gitignored) or the
environment -- never hardcoded, never committed.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE_ENV = _REPO_ROOT / "platform" / "infra" / "compose" / ".env"


class ObjectStoreError(RuntimeError):
    """Raised on a storage integrity failure (a read whose bytes don't hash to its key)."""


def _read_compose_env() -> dict[str, str]:
    """Parse platform/infra/compose/.env into a dict. Returns {} if absent."""
    if not _COMPOSE_ENV.exists():
        return {}
    out: dict[str, str] = {}
    for line in _COMPOSE_ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


@dataclass(frozen=True)
class ObjectStoreConfig:
    endpoint: str = "localhost:9000"
    access_key: str = "milexium_dev"
    secret_key: str = ""
    bucket: str = "milexium-artifacts"
    secure: bool = False  # dev MinIO is plain HTTP; a real deployment uses TLS

    @classmethod
    def from_compose_env(cls) -> "ObjectStoreConfig":
        env = _read_compose_env()
        return cls(
            access_key=env.get("MINIO_ROOT_USER", "milexium_dev"),
            secret_key=env.get("MINIO_ROOT_PASSWORD", ""),
        )


def minio_available() -> bool:
    try:
        import minio  # noqa: F401

        return True
    except Exception:
        return False


class MinioObjectStore:
    """Content-addressed S3 object store. Key == sha256(bytes)."""

    def __init__(self, config: ObjectStoreConfig | None = None) -> None:
        from minio import Minio  # lazy: only needed when actually storing

        self._config = config or ObjectStoreConfig.from_compose_env()
        self._client = Minio(
            self._config.endpoint,
            access_key=self._config.access_key,
            secret_key=self._config.secret_key,
            secure=self._config.secure,
        )
        if not self._client.bucket_exists(self._config.bucket):
            self._client.make_bucket(self._config.bucket)

    @property
    def bucket(self) -> str:
        return self._config.bucket

    def put(self, data: bytes) -> str:
        """Store bytes under their sha256 key; idempotent (same bytes -> same
        key, re-put is a no-op the store deduplicates). Returns the key."""
        key = hashlib.sha256(data).hexdigest()
        if not self.exists(key):
            self._client.put_object(
                self._config.bucket, key, io.BytesIO(data), length=len(data)
            )
        return key

    def get(self, key: str) -> bytes:
        """Fetch bytes and verify they hash back to `key` -- a corrupted or
        tampered object is caught here, never returned as if trustworthy."""
        response = self._client.get_object(self._config.bucket, key)
        try:
            data = response.read()
        finally:
            response.close()
            response.release_conn()
        actual = hashlib.sha256(data).hexdigest()
        if actual != key:
            raise ObjectStoreError(
                f"object integrity failure: key {key} but stored bytes hash to {actual}"
            )
        return data

    def exists(self, key: str) -> bool:
        from minio.error import S3Error

        try:
            self._client.stat_object(self._config.bucket, key)
            return True
        except S3Error:
            return False
