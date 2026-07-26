"""Estate catalog inventory and free-space reporting (blueprint 17
completion evidence #7 "inventoried ... through automated commands" and #8
"reports free-space ... before executing large transforms").

The catalog is the estate's source of truth for what is actually retained: it
reads the committed acquisition manifests and the per-dataset acquired-entry
records, and reports retained bytes, rights, and current disk headroom. It
never trusts a manifest's *expected* sizes as reality -- it reports what was
actually acquired.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from themis.estate.manifest import AcquisitionManifest, load_manifest

_REPO_ROOT = Path(__file__).resolve().parents[2]
# The governed estate lives under data/acquired/. data/curated/ holds the
# hand-acquired datasets that predate this pipeline (ADR-0053) and is NOT
# reachable from here -- nothing in curated/ came through quarantine.
_DATA = _REPO_ROOT / "data" / "acquired"
_CATALOG = _DATA / "catalog"


@dataclass(frozen=True)
class CatalogEntry:
    dataset_id: str
    manifest: AcquisitionManifest
    acquired: bool
    retained_bytes: int
    sha256: str | None
    rights: str
    # ADR-0032 object-store backing: the content address the raw object is
    # ALSO stored under in MinIO (== sha256), and its bucket. None for datasets
    # acquired local-disk-only (older records simply omit these fields).
    object_store_key: str | None = None
    object_store_bucket: str | None = None


def _acquired_record(dataset_id: str) -> dict | None:
    path = _CATALOG / f"{dataset_id}.acquired.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def inventory(catalog_dir: str | Path = _CATALOG) -> list[CatalogEntry]:
    """Every dataset with a committed manifest, joined to its acquired-record
    if it has been pulled yet. A manifest without an acquired-record is a
    queued dataset -- declared and rights-checked, not yet downloaded."""
    catalog_dir = Path(catalog_dir)
    entries: list[CatalogEntry] = []
    for manifest_path in sorted(catalog_dir.glob("*.manifest.json")):
        manifest = load_manifest(manifest_path)
        record = _acquired_record(manifest.dataset_id)
        entries.append(
            CatalogEntry(
                dataset_id=manifest.dataset_id,
                manifest=manifest,
                acquired=record is not None,
                retained_bytes=record["retained_bytes"] if record else 0,
                sha256=record["sha256"] if record else None,
                rights=manifest.license_and_commercial_rights,
                object_store_key=record.get("object_store_key") if record else None,
                object_store_bucket=record.get("object_store_bucket") if record else None,
            )
        )
    return entries


def free_space_report(path: str | Path = _DATA) -> dict:
    """Current disk headroom plus total retained estate bytes. Callable before
    any large transform so a job can refuse to run rather than fill the disk."""
    usage = shutil.disk_usage(path)
    retained = sum(e.retained_bytes for e in inventory())
    return {
        "disk_total_gb": round(usage.total / 1e9, 2),
        "disk_free_gb": round(usage.free / 1e9, 2),
        "estate_retained_gb": round(retained / 1e9, 4),
        "estate_datasets_cataloged": len(inventory()),
        "estate_datasets_acquired": sum(1 for e in inventory() if e.acquired),
    }
