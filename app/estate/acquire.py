"""Manifest-gated acquisition (blueprint 17: quarantine -> validate -> raw).

The acquisition sequence enforces the blueprint's non-negotiables:

1. A valid manifest with declared rights is required -- no manifest, no bytes.
2. Free space is checked and reported *before* the download starts
   (completion evidence #8: "reports free-space ... before executing large
   transforms"); acquisition refuses if it would leave less headroom than the
   configured floor.
3. The object downloads into `data/quarantine/` first -- "untrusted inputs
   awaiting validation" -- never straight into the trusted raw zone.
4. Its sha256 is computed and, if the manifest declared an expected checksum,
   compared; a mismatch leaves the object in quarantine and raises, so
   corrupt/tampered/unexpected content can never silently enter the estate.
5. Only after validation is the object atomically moved into its manifest's
   zone under a content-addressed name, and a catalog entry (with the real
   retained byte count and computed checksum) is written.

Network downloads use the same `curl` already relied on elsewhere in this
repo's fetch scripts. This module deliberately handles one object per call;
incremental/streaming acquisition is Specified, not built.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.estate.manifest import AcquisitionManifest, load_manifest
from app.estate.object_store import (
    MinioObjectStore,
    ObjectStoreConfig,
    minio_available,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATA = _REPO_ROOT / "data"
_QUARANTINE = _DATA / "quarantine"
_CATALOG = _DATA / "catalog"

_DEFAULT_FREE_FLOOR_GB = 20.0


class AcquisitionError(RuntimeError):
    """Raised when acquisition fails validation (checksum, download, rights)."""


class FreeSpaceError(AcquisitionError):
    """Raised when acquiring would drop free space below the configured floor."""


@dataclass(frozen=True)
class AcquisitionResult:
    dataset_id: str
    raw_path: Path
    sha256: str
    retained_bytes: int
    catalog_entry_path: Path
    object_store_key: str | None = None


def _free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / 1e9


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_object_store() -> MinioObjectStore | None:
    """Build a MinIO-backed store from platform/infra/compose/.env, or return None when
    the optional `minio` client, its credentials, or the container are absent.

    Returning None keeps local disk authoritative and lets acquisition proceed
    byte-for-byte unchanged (ADR-0032: local disk is the default; the free,
    already-running MinIO is an additive backing, never a hard dependency).
    """
    if not minio_available():
        return None
    config = ObjectStoreConfig.from_compose_env()
    if not config.secret_key:
        return None
    try:
        return MinioObjectStore(config)
    except Exception:  # noqa: BLE001 -- unreachable container => skip backing, don't fail acquisition
        return None


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # -f: fail on HTTP error instead of saving an error page as if it were data
    # (blueprint 17: malformed/unexpected inputs must be caught, never trusted).
    result = subprocess.run(
        ["curl", "-fL", "--retry", "3", "--retry-delay", "2", "-o", str(dest), url],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        dest.unlink(missing_ok=True)
        raise AcquisitionError(f"download failed for {url}: curl exit {result.returncode}: {result.stderr.strip()}")


def acquire(
    manifest_path: str | Path,
    *,
    free_floor_gb: float = _DEFAULT_FREE_FLOOR_GB,
    downloader=_download,
    object_store: MinioObjectStore | None = None,
    back_with_object_store: bool = False,
) -> AcquisitionResult:
    """Acquire one dataset through the full governed sequence. `downloader` is
    injectable so tests can exercise the pipeline (quarantine, checksum,
    promotion, catalog) without hitting the network.

    Object-store backing (ADR-0032) is additive and OFF by default: local disk
    is always authoritative. Pass an explicit `object_store` (a MinioObjectStore
    -- what tests inject), or `back_with_object_store=True` to auto-resolve the
    free, already-running MinIO from platform/infra/compose/.env. When neither the client
    nor the container nor its creds are present, backing is silently skipped and
    acquisition proceeds byte-for-byte as the local-disk path."""
    manifest = load_manifest(manifest_path)

    target_zone = _DATA / manifest.zone
    free_before = _free_gb(_DATA)
    projected_after = free_before - manifest.expected_expanded_gb
    if projected_after < free_floor_gb:
        raise FreeSpaceError(
            f"acquiring {manifest.dataset_id} (~{manifest.expected_expanded_gb} GB expanded) "
            f"would leave ~{projected_after:.1f} GB free, below the {free_floor_gb} GB floor "
            f"(currently {free_before:.1f} GB free)"
        )

    _QUARANTINE.mkdir(parents=True, exist_ok=True)
    suffix = Path(manifest.source_url).suffix or ".bin"
    quarantined = _QUARANTINE / f"{manifest.dataset_id}{suffix}"
    downloader(manifest.source_url, quarantined)

    checksum = _sha256_file(quarantined)
    if manifest.source_checksum is not None and checksum != manifest.source_checksum:
        raise AcquisitionError(
            f"{manifest.dataset_id}: sha256 mismatch -- manifest expected "
            f"{manifest.source_checksum}, downloaded object is {checksum}; "
            f"object left in quarantine at {quarantined}"
        )

    retained_bytes = quarantined.stat().st_size
    target_zone.mkdir(parents=True, exist_ok=True)
    # content-addressed name: prefix keeps it human-scannable, hash makes it
    # immutable and dedup-detectable (blueprint 17: "Raw objects are immutable
    # and content-addressed").
    raw_path = target_zone / f"{manifest.dataset_id}.{checksum[:16]}{suffix}"
    shutil.move(str(quarantined), str(raw_path))

    entry = {
        "dataset_id": manifest.dataset_id,
        "acquired_at": datetime.now(timezone.utc).isoformat(),
        "source_url": manifest.source_url,
        "zone": manifest.zone,
        "raw_path": str(raw_path.relative_to(_REPO_ROOT)),
        "sha256": checksum,
        "retained_bytes": retained_bytes,
        "license_and_commercial_rights": manifest.license_and_commercial_rights,
        "free_gb_before": round(free_before, 2),
        "free_gb_after": round(_free_gb(_DATA), 2),
    }

    # Additive MinIO backing (ADR-0032). The raw zone stays authoritative; if a
    # store is available we ALSO mirror the just-promoted object into it,
    # content-addressed. The object-store key IS the sha256 we already computed
    # -- the estate key and the object-store key are the SAME content address --
    # so this is dedup-safe and tamper-evident on read. When no store is
    # configured, the entry below is byte-for-byte the original local-disk path.
    store = object_store
    if store is None and back_with_object_store:
        store = _resolve_object_store()
    object_store_key: str | None = None
    if store is not None:
        object_store_key = store.put(raw_path.read_bytes())
        if object_store_key != checksum:
            raise AcquisitionError(
                f"{manifest.dataset_id}: object-store key {object_store_key} does not "
                f"equal the estate content address {checksum}; the raw zone key and the "
                "object-store key must be the same sha256 (blueprint 17 / ADR-0032)"
            )
        entry["object_store_key"] = object_store_key
        entry["object_store_bucket"] = store.bucket

    _CATALOG.mkdir(parents=True, exist_ok=True)
    entry_path = _CATALOG / f"{manifest.dataset_id}.acquired.json"
    entry_path.write_text(json.dumps(entry, indent=2, sort_keys=True), encoding="utf-8")

    return AcquisitionResult(
        dataset_id=manifest.dataset_id,
        raw_path=raw_path,
        sha256=checksum,
        retained_bytes=retained_bytes,
        catalog_entry_path=entry_path,
        object_store_key=object_store_key,
    )
