"""Estate governance conformance (Program C data-estate layer, blueprint 17).

Proves the acquisition pipeline actually *enforces* governance rather than
just documenting it: a manifest without declared rights is rejected, a
free-space floor blocks an oversized acquisition, a checksum mismatch leaves
the object in quarantine instead of the trusted zone, and a clean acquisition
records real retained bytes + checksum in the catalog. The downloader is
injected so these run offline and deterministically.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from themis.estate import acquire, load_manifest
from themis.estate.acquire import AcquisitionError, FreeSpaceError
from themis.estate.manifest import ManifestError


_VALID_MANIFEST = {
    "dataset_id": "test-dataset",
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


def _write_manifest(tmp_path: Path, overrides: dict | None = None) -> Path:
    data = dict(_VALID_MANIFEST)
    if overrides:
        data.update(overrides)
    path = tmp_path / f"{data['dataset_id']}.manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_manifest_with_undeclared_rights_is_rejected(tmp_path: Path) -> None:
    path = _write_manifest(tmp_path, {"license_and_commercial_rights": "unknown"})
    with pytest.raises(ManifestError, match="rights"):
        load_manifest(path)


def test_manifest_missing_a_governance_field_is_rejected(tmp_path: Path) -> None:
    data = dict(_VALID_MANIFEST)
    del data["retention_and_deletion"]
    path = tmp_path / "bad.manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ManifestError):
        load_manifest(path)


def test_free_space_floor_blocks_an_oversized_acquisition(tmp_path: Path) -> None:
    # Claim a download larger than any real disk so the floor always trips,
    # proving the guard fires *before* any download is attempted.
    path = _write_manifest(
        tmp_path, {"dataset_id": "huge-dataset", "expected_expanded_gb": 10_000_000.0}
    )

    def _must_not_be_called(url, dest):
        raise AssertionError("downloader ran despite the free-space floor being exceeded")

    with pytest.raises(FreeSpaceError):
        acquire(path, downloader=_must_not_be_called)


def test_checksum_mismatch_leaves_object_in_quarantine(tmp_path: Path) -> None:
    path = _write_manifest(
        tmp_path,
        {
            "dataset_id": "checksum-test",
            "source_checksum": "0" * 64,  # deliberately wrong
        },
    )

    def _fake_download(url, dest):
        Path(dest).write_bytes(b"real content that will not match the fake checksum")

    # free_floor_gb=0: this test is about the checksum guard, not free space --
    # a CI runner with little free disk must not trip the space floor first.
    with pytest.raises(AcquisitionError, match="sha256 mismatch"):
        acquire(path, downloader=_fake_download, free_floor_gb=0.0)

    repo_root = Path(__file__).resolve().parents[3]
    # object stayed in quarantine, never reached the trusted standards zone
    assert (repo_root / "data" / "acquired" / "quarantine" / "checksum-test.csv").exists()
    promoted = list((repo_root / "data" / "acquired" / "standards").glob("checksum-test.*"))
    assert promoted == []

    # cleanup so a re-run starts clean
    (repo_root / "data" / "acquired" / "quarantine" / "checksum-test.csv").unlink(missing_ok=True)


def test_clean_acquisition_promotes_and_catalogs(tmp_path: Path) -> None:
    content = b"col_a,col_b\n1,2\n"
    import hashlib

    expected = hashlib.sha256(content).hexdigest()
    path = _write_manifest(
        tmp_path, {"dataset_id": "clean-test", "source_checksum": expected}
    )

    def _fake_download(url, dest):
        Path(dest).write_bytes(content)

    # free_floor_gb=0: about promotion/catalog, not free space (see above).
    result = acquire(path, downloader=_fake_download, free_floor_gb=0.0)

    assert result.sha256 == expected
    assert result.retained_bytes == len(content)
    assert result.raw_path.exists()
    assert result.raw_path.read_bytes() == content
    assert result.catalog_entry_path.exists()
    entry = json.loads(result.catalog_entry_path.read_text(encoding="utf-8"))
    assert entry["sha256"] == expected
    assert entry["retained_bytes"] == len(content)
    assert "commercial use permitted" in entry["license_and_commercial_rights"]

    # cleanup
    result.raw_path.unlink(missing_ok=True)
    result.catalog_entry_path.unlink(missing_ok=True)
