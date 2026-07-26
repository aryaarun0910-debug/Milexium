"""Governance conformance for the US open-data acquisitions (MX-C-US-OPENDATA-006).

The estate's promise is that *every retained byte carries a manifest stating
real rights, and the catalog record matches what is actually on disk*. These
tests hold that promise to the six datasets acquired in this packet, rather
than trusting that the acquisition ran cleanly once.

Three properties are asserted:

1. Every manifest added by this packet loads through `load_manifest` -- i.e.
   it passes the full pydantic contract *and* the rights gate.
2. Its `license_and_commercial_rights` is a real statement, not a placeholder
   dressed up to slip past the gate. `rights_are_declared()` only rejects the
   literal words "unknown"/"tbd"/"todo"/"?"; a manifest saying "open source"
   would pass it and still tell an auditor nothing. So these tests additionally
   require the field to name a licence and take an explicit position on
   commercial use.
3. Where a dataset has actually been acquired, the catalog record's sha256 and
   retained_bytes match the bytes on disk *now* -- the check that catches a
   truncated re-download, a partially-written promotion, or silent corruption.

Datasets that are declared but not yet downloaded (manifest present, no
acquired-record) skip cleanly: a queued dataset is a legitimate state in this
estate (data/acquired/README.md), and the raw zones are gitignored, so a fresh clone
runs these tests with nothing on disk and must still pass.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from themis.estate.manifest import AcquisitionManifest, load_manifest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CATALOG = _REPO_ROOT / "data" / "acquired" / "catalog"

# The datasets this packet declared. Named explicitly rather than globbed so a
# later packet's manifest cannot silently inherit (or silently escape) these
# assertions.
US_OPENDATA_DATASETS = (
    "ntd-monthly-ridership-all-modes",
    "ntd-service-opex-by-mode-timeseries",
    "ntd-gtfs-weblinks",
    "mobility-database-catalog",
    "ntm-stops-national",
    "ntm-routes-national",
)

# A rights statement has to say WHICH licence and WHETHER commercial use is
# allowed. These are the licence families this packet actually acquired under;
# a new dataset under a different licence should extend this list deliberately.
_LICENCE_MARKERS = (
    "public domain",
    "usgov_works",
    "apache-2.0",
    "17 u.s.c.",
)
_COMMERCIAL_MARKERS = (
    "commercial use is permitted",
    "commercial use permitted",
    "commercial use is not permitted",
    "commercial use is restricted",
)


def _manifest_path(dataset_id: str) -> Path:
    return _CATALOG / f"{dataset_id}.manifest.json"


def _acquired_path(dataset_id: str) -> Path:
    return _CATALOG / f"{dataset_id}.acquired.json"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@pytest.mark.parametrize("dataset_id", US_OPENDATA_DATASETS)
def test_manifest_exists_and_loads(dataset_id: str) -> None:
    """The manifest is committed and passes the whole governance contract.

    load_manifest raises ManifestError on a missing field, a bad zone, or an
    undeclared-rights value, so a clean load IS the governance assertion.
    """
    path = _manifest_path(dataset_id)
    assert path.exists(), f"{dataset_id}: manifest is not committed to data/acquired/catalog/"
    manifest = load_manifest(path)
    assert manifest.dataset_id == dataset_id
    assert manifest.rights_are_declared()


@pytest.mark.parametrize("dataset_id", US_OPENDATA_DATASETS)
def test_rights_statement_is_real_not_a_placeholder(dataset_id: str) -> None:
    """Rights must name a licence and state a commercial-use position.

    This is stricter than `rights_are_declared()` on purpose. The base gate
    only blocks the literal placeholder words; a governance record whose rights
    field reads "open data" is technically past that gate and still useless to
    an auditor deciding whether Milexium may resell a derived product.
    """
    manifest = load_manifest(_manifest_path(dataset_id))
    rights = manifest.license_and_commercial_rights.lower()

    assert len(rights) > 80, (
        f"{dataset_id}: rights statement is {len(rights)} chars -- too short to "
        "identify a licence and a commercial-use position"
    )
    assert any(m in rights for m in _LICENCE_MARKERS), (
        f"{dataset_id}: rights statement names no recognised licence "
        f"(looked for {_LICENCE_MARKERS}); got {manifest.license_and_commercial_rights!r}"
    )
    assert any(m in rights for m in _COMMERCIAL_MARKERS), (
        f"{dataset_id}: rights statement takes no explicit position on commercial "
        f"use; got {manifest.license_and_commercial_rights!r}"
    )


@pytest.mark.parametrize("dataset_id", US_OPENDATA_DATASETS)
def test_manifest_declares_purpose_and_provenance(dataset_id: str) -> None:
    """Every field that answers "why do we hold this" must be substantive.

    A manifest that loads but says nothing is a governance record in name only.
    """
    manifest = load_manifest(_manifest_path(dataset_id))
    assert manifest.decision_tasks_enabled, f"{dataset_id}: no decision task declared"
    assert manifest.source_url.startswith("https://"), (
        f"{dataset_id}: source_url must be an https URL for provenance to be checkable"
    )
    assert manifest.canonical_contract.strip(), f"{dataset_id}: canonical_contract is empty"
    assert manifest.acceptance_threshold.strip(), f"{dataset_id}: acceptance_threshold is empty"
    assert manifest.retention_and_deletion.strip(), f"{dataset_id}: retention policy is empty"
    assert manifest.expected_retained_gb > 0, (
        f"{dataset_id}: expected_retained_gb is 0 -- the free-space guard cannot "
        "reason about a dataset that claims to occupy nothing"
    )


@pytest.mark.parametrize("dataset_id", US_OPENDATA_DATASETS)
def test_acquired_object_checksum_matches_disk(dataset_id: str) -> None:
    """The catalog's content address must match the bytes actually on disk.

    Skips when the dataset is declared but not acquired (a legitimate "queued"
    state), and when the acquired-record exists but the raw zone has been
    evicted -- the raw zones are gitignored, so a fresh clone has the catalog
    without the bytes and must not fail here.
    """
    acquired_path = _acquired_path(dataset_id)
    if not acquired_path.exists():
        pytest.skip(f"{dataset_id}: declared but not acquired (queued dataset)")

    entry = json.loads(acquired_path.read_text(encoding="utf-8"))
    raw_path = _REPO_ROOT / entry["raw_path"]
    if not raw_path.exists():
        pytest.skip(f"{dataset_id}: acquired-record present but raw object not on this disk")

    assert raw_path.stat().st_size == entry["retained_bytes"], (
        f"{dataset_id}: catalog says {entry['retained_bytes']} bytes, disk has "
        f"{raw_path.stat().st_size} -- the object changed after promotion"
    )
    assert _sha256_file(raw_path) == entry["sha256"], (
        f"{dataset_id}: sha256 of {raw_path} does not match the catalog record; "
        "the retained object is not the object that was validated"
    )
    # Content-addressed naming: the promoted filename carries its own digest,
    # so a mismatched pair is detectable without reading the whole file.
    assert entry["sha256"][:16] in raw_path.name, (
        f"{dataset_id}: promoted filename {raw_path.name} does not carry the "
        "content address -- the estate's immutability convention is broken"
    )


@pytest.mark.parametrize("dataset_id", US_OPENDATA_DATASETS)
def test_acquired_record_rights_match_the_manifest(dataset_id: str) -> None:
    """The rights travel with the acquisition, not just with the manifest.

    acquire() copies the rights statement into the acquired-record precisely so
    that an auditor reading the ledger never has to trust that the manifest was
    not edited afterwards. Divergence means one of the two is stale.
    """
    acquired_path = _acquired_path(dataset_id)
    if not acquired_path.exists():
        pytest.skip(f"{dataset_id}: declared but not acquired (queued dataset)")

    entry = json.loads(acquired_path.read_text(encoding="utf-8"))
    manifest = load_manifest(_manifest_path(dataset_id))
    assert entry["license_and_commercial_rights"] == manifest.license_and_commercial_rights, (
        f"{dataset_id}: the acquired-record's rights statement has drifted from the "
        "manifest; re-acquire or reconcile rather than leaving two versions of the "
        "governance record"
    )
    assert entry["zone"] == manifest.zone
    assert entry["source_url"] == manifest.source_url


def test_every_catalog_manifest_in_the_estate_still_loads() -> None:
    """Regression guard for the whole ledger, not just this packet's rows.

    Adding six manifests must not break the estate's existing ones, and a later
    hand-edit to any manifest should fail here rather than at acquisition time.
    """
    manifests = sorted(_CATALOG.glob("*.manifest.json"))
    assert manifests, "data/acquired/catalog/ has no manifests -- the governance ledger is empty"
    for path in manifests:
        manifest = load_manifest(path)
        assert isinstance(manifest, AcquisitionManifest)
        assert manifest.dataset_id == path.name[: -len(".manifest.json")], (
            f"{path.name}: filename and dataset_id disagree, so the ledger cannot "
            "be indexed by dataset_id"
        )
