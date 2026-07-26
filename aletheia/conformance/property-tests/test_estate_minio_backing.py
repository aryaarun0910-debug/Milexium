"""Estate raw-zone MinIO backing conformance (Program C, blueprint 17 / ADR-0032).

Proves the additive object-store backing: when acquire() promotes a validated
object into the raw zone it ALSO mirrors it, content-addressed, into the free
already-running MinIO -- under the SAME sha256 that is the estate's own content
address -- and records that key in the catalog. The downloader is injected so
these run offline; only the object-store round-trip touches MinIO.

Skips cleanly (mirroring test_object_store.py) when the optional `minio` client,
its credentials (talos/infra/compose/.env), or the container are absent -- so the
local-disk path stays the default and the suite stays green without the dev
stack up. A companion test proves that with backing OFF acquisition still
succeeds and records no object-store key at all (byte-for-byte local disk).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

minio = pytest.importorskip("minio")  # noqa: F841 -- skip whole module if extra absent

from themis.estate import acquire, inventory  # noqa: E402
from themis.estate.object_store import (  # noqa: E402
    MinioObjectStore,
    ObjectStoreConfig,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
# Must match themis/estate/{acquire,catalog}.py exactly: the governed estate
# roots at data/acquired/. If these drift apart the test writes a manifest
# somewhere inventory() never looks, and fails for a reason that has nothing
# to do with MinIO.
_DATA = _REPO_ROOT / "data" / "acquired"
_CATALOG = _DATA / "catalog"

_VALID_MANIFEST = {
    "dataset_id": "minio-backing-test",
    "owner_and_source": "test source",
    "license_and_commercial_rights": "CC0-1.0; commercial use permitted",
    "decision_tasks_enabled": ["connect.standards_conformance"],
    "geography": "n/a",
    "time_coverage": "n/a",
    "source_url": "https://example.invalid/test.csv",
    "expected_download_gb": 0.0,
    "expected_expanded_gb": 0.0,
    "expected_retained_gb": 0.0,
    "schema_and_format": "CSV",
    "sensitive_fields": [],
    "update_frequency": "never",
    "source_checksum": None,
    "canonical_contract": "none-yet",
    "quality_tests": [],
    "acceptance_threshold": "non-empty",
    "retention_and_deletion": "cheaply reproducible",
    "derived_artifacts": [],
    "zone": "standards",
}


def _store_or_skip() -> MinioObjectStore:
    """Mirror test_object_store.py: skip (never fail) when MinIO is unconfigured
    or unreachable, so the default local-disk path needs no dev stack."""
    cfg = ObjectStoreConfig.from_compose_env()
    if not cfg.secret_key:
        pytest.skip("talos/infra/compose/.env not present -- MinIO dev stack not configured")
    try:
        return MinioObjectStore(cfg)
    except Exception as exc:  # noqa: BLE001 -- any connection failure => skip, not fail
        pytest.skip(f"MinIO not reachable ({type(exc).__name__}) -- dev stack not up")


def _write_manifest(directory: Path, overrides: dict | None = None) -> Path:
    data = dict(_VALID_MANIFEST)
    if overrides:
        data.update(overrides)
    path = directory / f"{data['dataset_id']}.manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_backed_acquisition_mirrors_raw_object_into_minio() -> None:
    """With an object store provided, a clean acquisition lands the object in
    the raw zone AND in MinIO under its sha256; the catalog records
    object_store_key == the sha256; and store.get(key) round-trips the raw
    bytes. inventory() surfaces the key so the estate catalog stays the record."""
    store = _store_or_skip()

    content = b"col_a,col_b\n7,11\nmilexium raw-zone -> minio\n"
    expected = hashlib.sha256(content).hexdigest()

    def _fake_download(url, dest):  # injected: never hits the network
        Path(dest).write_bytes(content)

    # Manifest lives in the real catalog dir so inventory() (default) joins it to
    # the acquired record; cleaned up in finally, mirroring test_estate_acquisition.
    _CATALOG.mkdir(parents=True, exist_ok=True)
    manifest_path = _write_manifest(_CATALOG)
    try:
        # free_floor_gb=0: this test is about backing, not the space guard.
        result = acquire(
            manifest_path,
            downloader=_fake_download,
            free_floor_gb=0.0,
            object_store=store,
        )

        # 1. local disk stays authoritative -- object is in the raw zone.
        assert result.raw_path.exists()
        assert result.raw_path.read_bytes() == content
        assert result.sha256 == expected

        # 2. the estate key and the object-store key are the SAME content address.
        assert result.object_store_key == expected
        assert store.exists(expected)
        assert store.get(expected) == content  # verified round-trip out of MinIO

        # 3. the catalog entry records the object-store key + bucket.
        entry = json.loads(result.catalog_entry_path.read_text(encoding="utf-8"))
        assert entry["object_store_key"] == expected
        assert entry["object_store_bucket"] == store.bucket

        # 4. catalog.py surfaces it through inventory().
        cataloged = {e.dataset_id: e for e in inventory()}
        assert "minio-backing-test" in cataloged
        assert cataloged["minio-backing-test"].object_store_key == expected
        assert cataloged["minio-backing-test"].object_store_bucket == store.bucket
    finally:
        result_raw = _CATALOG.parent / "standards"
        for p in result_raw.glob("minio-backing-test.*"):
            p.unlink(missing_ok=True)
        (_CATALOG / "minio-backing-test.manifest.json").unlink(missing_ok=True)
        (_CATALOG / "minio-backing-test.acquired.json").unlink(missing_ok=True)


def test_unbacked_acquisition_records_no_object_store_key(tmp_path: Path) -> None:
    """With backing OFF (the default), acquisition still succeeds via local disk
    and records no object-store key -- the local-disk path is unchanged."""
    content = b"col_a,col_b\n1,2\n"
    expected = hashlib.sha256(content).hexdigest()

    def _fake_download(url, dest):
        Path(dest).write_bytes(content)

    manifest_path = _write_manifest(tmp_path, {"dataset_id": "unbacked-test"})
    try:
        result = acquire(manifest_path, downloader=_fake_download, free_floor_gb=0.0)

        assert result.raw_path.exists()
        assert result.sha256 == expected
        assert result.object_store_key is None

        entry = json.loads(result.catalog_entry_path.read_text(encoding="utf-8"))
        assert "object_store_key" not in entry
        assert "object_store_bucket" not in entry
    finally:
        result.raw_path.unlink(missing_ok=True)
        result.catalog_entry_path.unlink(missing_ok=True)
