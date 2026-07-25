"""Governance conformance for the Cal-ITP GTFS acquisitions (MX-C-GTFS-BLOCK-HARVEST-010).

The estate's promise is that no byte is held without declared rights, and that
the ledger matches what is actually on disk. `test_us_opendata_manifests.py`
holds that promise for the US federal public-domain acquisitions; this file
holds it for the seven Cal-ITP objects, which are the estate's first holding
under a *licence* rather than a public-domain dedication -- and a licence has
conditions a public-domain dedication does not.

That difference is what most of these tests are about. CC-BY obliges an
attribution, so the manifest has to name the attribution; the publisher stated
an intended use, so the manifest has to carry it verbatim; and the grant covers
Caltrans' aggregation and NOT the ~200 upstream operator feeds it was built
from, so the manifest has to say that too or a later reader will treat this
record as permission to go fetch agency feeds directly.

The version finding is asserted rather than narrated: the acquisition plan
expected data.ca.gov's CKAN record to pin the CC-BY version and it does not, so
the manifests must record the version choice as OURS. A governance record that
silently claimed "CC-BY 4.0" would be asserting something the publisher never
said.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from packages.estate.manifest import load_manifest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CATALOG = _REPO_ROOT / "data" / "catalog"

#: Named explicitly, never globbed: a later packet's manifest must not be able
#: to silently inherit -- or silently escape -- these assertions.
CALITP_DATASETS = (
    "calitp-gtfs-trips",
    "calitp-gtfs-stop-times",
    "calitp-gtfs-stops",
    "calitp-gtfs-routes",
    "calitp-gtfs-agency",
    "calitp-gtfs-frequencies",
    "calitp-gtfs-datasets",
)

#: The one object the whole packet turns on. Kept separate because "block_id
#: exists" is a claim about trips.csv specifically, not about the family.
_BLOCK_BEARING_DATASET = "calitp-gtfs-trips"


def _manifest_path(dataset_id: str) -> Path:
    return _CATALOG / f"{dataset_id}.manifest.json"


def _acquired_path(dataset_id: str) -> Path:
    return _CATALOG / f"{dataset_id}.acquired.json"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@pytest.mark.parametrize("dataset_id", CALITP_DATASETS)
def test_manifest_exists_and_passes_the_governance_gate(dataset_id: str) -> None:
    path = _manifest_path(dataset_id)
    assert path.exists(), f"{dataset_id}: manifest is not committed to data/catalog/"
    manifest = load_manifest(path)
    assert manifest.dataset_id == dataset_id
    assert manifest.rights_are_declared()
    assert manifest.zone == "raw/public"


@pytest.mark.parametrize("dataset_id", CALITP_DATASETS)
def test_rights_name_the_licence_and_take_a_commercial_position(dataset_id: str) -> None:
    """Stricter than `rights_are_declared()`, which only blocks the literal
    words unknown/tbd/todo/?. A field reading "open data" clears that gate and
    tells an auditor nothing about whether Milexium may sell a derived product.
    """
    rights = load_manifest(_manifest_path(dataset_id)).license_and_commercial_rights.lower()
    assert "creative commons attribution" in rights and "cc-by" in rights
    assert "commercial use is permitted" in rights


@pytest.mark.parametrize("dataset_id", CALITP_DATASETS)
def test_rights_cite_the_machine_readable_field_they_were_read_from(dataset_id: str) -> None:
    """Provenance for the RIGHTS, not just for the bytes. "It's CC-BY" is an
    assertion; "the publisher's CKAN record returns license_id='cc-by' at this
    URL" is checkable by the next person, which is the whole point of a
    governance ledger."""
    rights = load_manifest(_manifest_path(dataset_id)).license_and_commercial_rights
    assert "data.ca.gov/api/3/action/package_show" in rights
    assert "license_id='cc-by'" in rights
    assert "'No restrictions on public use'" in rights


@pytest.mark.parametrize("dataset_id", CALITP_DATASETS)
def test_rights_record_the_version_as_our_choice_not_the_publishers(dataset_id: str) -> None:
    """THE FINDING THIS PACKET OVERTURNED. data/ACQUISITION_PLAN.md said to
    "capture license_id / license_url from the CKAN API into the manifest
    rather than assuming 4.0". We did, and the CKAN license_url is the Open
    Definition's *version-agnostic* cc-by entry -- so the version still is not
    pinned by the source. Recording "CC-BY 4.0" as though Caltrans had declared
    it would put a claim in the ledger that the publisher never made."""
    rights = load_manifest(_manifest_path(dataset_id)).license_and_commercial_rights
    assert "opendefinition.org/licenses/cc-by" in rights
    assert "https://creativecommons.org/licenses/by/4.0/" in rights, (
        "the licence text actually attributed under must be named by URL"
    )
    lowered = rights.lower()
    assert "not pinned by the source" in lowered
    assert "our choice" in lowered


@pytest.mark.parametrize("dataset_id", CALITP_DATASETS)
def test_rights_carry_the_attribution_cc_by_actually_obliges(dataset_id: str) -> None:
    """CC-BY is a licence with a condition. A manifest that records the grant
    and omits the obligation records half the contract."""
    rights = load_manifest(_manifest_path(dataset_id)).license_and_commercial_rights
    assert "attribution" in rights.lower()
    assert "California Integrated Travel Program" in rights
    assert "California Department of Transportation" in rights


@pytest.mark.parametrize("dataset_id", CALITP_DATASETS)
def test_rights_carry_the_publishers_stated_use_limit_verbatim(dataset_id: str) -> None:
    """Caltrans states this assembly is "for analysis purposes only. Do not use
    for trip planner ingestion". That is not a CC-BY term and does not restrict
    commercial use -- but it is the publisher's stated intent about their own
    data, and dropping it from the record would let a later reader wire these
    bytes into a passenger-facing planner without ever seeing the sentence."""
    rights = load_manifest(_manifest_path(dataset_id)).license_and_commercial_rights
    assert "Do not use for trip planner ingestion" in rights
    assert "trip planner" in rights.lower()


@pytest.mark.parametrize("dataset_id", CALITP_DATASETS)
def test_rights_refuse_to_launder_the_upstream_operator_feeds(dataset_id: str) -> None:
    """The exact mistake this record must not enable. Caltrans licenses ITS
    aggregation under CC-BY; the ~200 operator feeds it was assembled from keep
    their own terms, several of which (CTA-style revocable click-throughs) the
    estate has already refused. Without this scope limit, a future packet would
    read "California GTFS is CC-BY" and start fetching agency feeds directly."""
    rights = load_manifest(_manifest_path(dataset_id)).license_and_commercial_rights
    lowered = rights.lower()
    assert "scope limit" in lowered
    assert "own upstream terms" in lowered
    assert "does not launder" in lowered


def test_every_calitp_manifest_carries_byte_identical_rights() -> None:
    """Seven objects, one grant, one sentence. Divergence between them would
    mean the ledger has seven slightly different answers to a single legal
    question -- and the one an auditor happens to read would be luck."""
    statements = {
        dataset_id: load_manifest(_manifest_path(dataset_id)).license_and_commercial_rights
        for dataset_id in CALITP_DATASETS
    }
    distinct = set(statements.values())
    assert len(distinct) == 1, (
        "the Cal-ITP rights statement has drifted between manifests: "
        f"{ {k: len(v) for k, v in statements.items()} }"
    )


@pytest.mark.parametrize("dataset_id", CALITP_DATASETS)
def test_manifest_declares_purpose_provenance_and_a_real_footprint(dataset_id: str) -> None:
    manifest = load_manifest(_manifest_path(dataset_id))
    assert manifest.decision_tasks_enabled
    assert manifest.source_url.startswith("https://data.ca.gov/")
    assert manifest.canonical_contract.strip()
    assert manifest.acceptance_threshold.strip()
    assert manifest.retention_and_deletion.strip()
    assert manifest.expected_retained_gb > 0, (
        "the free-space guard cannot reason about a dataset claiming to occupy nothing"
    )
    assert manifest.quality_tests, f"{dataset_id}: no quality test declared"


@pytest.mark.parametrize("dataset_id", CALITP_DATASETS)
def test_acquisition_needs_no_credential(dataset_id: str) -> None:
    """HARD CONSTRAINT from the founder: no paid services, no registration, no
    billing-enabled cloud. A source_url carrying a key or token would be the
    first sign that constraint had been quietly broken."""
    url = load_manifest(_manifest_path(dataset_id)).source_url
    lowered = url.lower()
    for marker in ("api_key", "apikey", "token=", "access_key", "&key=", "?key="):
        assert marker not in lowered, f"{dataset_id}: source_url looks credentialed ({marker})"


@pytest.mark.parametrize("dataset_id", CALITP_DATASETS)
def test_acquired_object_matches_the_ledger(dataset_id: str) -> None:
    """Catches a truncated re-download, a half-written promotion, or silent
    corruption. Skips cleanly on a fresh clone: raw zones are gitignored, so the
    catalog travels without the bytes and must still pass."""
    acquired_path = _acquired_path(dataset_id)
    if not acquired_path.exists():
        pytest.skip(f"{dataset_id}: declared but not acquired (queued dataset)")
    entry = json.loads(acquired_path.read_text(encoding="utf-8"))
    raw_path = _REPO_ROOT / entry["raw_path"]
    if not raw_path.exists():
        pytest.skip(f"{dataset_id}: acquired-record present but raw object not on this disk")

    assert raw_path.stat().st_size == entry["retained_bytes"]
    assert _sha256_file(raw_path) == entry["sha256"]
    assert entry["sha256"][:16] in raw_path.name, (
        "the promoted filename must carry its own content address"
    )


@pytest.mark.parametrize("dataset_id", CALITP_DATASETS)
def test_acquired_record_rights_have_not_drifted_from_the_manifest(dataset_id: str) -> None:
    acquired_path = _acquired_path(dataset_id)
    if not acquired_path.exists():
        pytest.skip(f"{dataset_id}: declared but not acquired (queued dataset)")
    entry = json.loads(acquired_path.read_text(encoding="utf-8"))
    manifest = load_manifest(_manifest_path(dataset_id))
    assert entry["license_and_commercial_rights"] == manifest.license_and_commercial_rights, (
        "a post-hoc manifest edit has left two disagreeing versions of the ledger"
    )
    assert entry["zone"] == manifest.zone
    assert entry["source_url"] == manifest.source_url


@pytest.mark.parametrize("dataset_id", CALITP_DATASETS)
def test_object_store_key_is_the_same_content_address(dataset_id: str) -> None:
    """ADR-0032: the estate key and the MinIO key are the SAME sha256, so the
    mirror is dedup-safe and tamper-evident. Local MinIO only -- the founder's
    no-paid-cloud constraint means this must never become an S3/GCS bucket."""
    acquired_path = _acquired_path(dataset_id)
    if not acquired_path.exists():
        pytest.skip(f"{dataset_id}: declared but not acquired (queued dataset)")
    entry = json.loads(acquired_path.read_text(encoding="utf-8"))
    if "object_store_key" not in entry:
        pytest.skip(f"{dataset_id}: acquired local-disk-only (no object store configured)")
    assert entry["object_store_key"] == entry["sha256"]


def test_the_block_bearing_object_actually_contains_block_ids() -> None:
    """The packet's load-bearing acceptance threshold, checked against bytes.

    Everything downstream assumes trips.csv has a `block_id` column with at
    least some values in it. A schema change upstream that dropped or renamed
    the column would otherwise surface as "scheduled deadhead fell to zero",
    which reads like a finding rather than a broken input.
    """
    acquired_path = _acquired_path(_BLOCK_BEARING_DATASET)
    if not acquired_path.exists():
        pytest.skip("trips not acquired")
    entry = json.loads(acquired_path.read_text(encoding="utf-8"))
    raw_path = _REPO_ROOT / entry["raw_path"]
    if not raw_path.exists():
        pytest.skip("trips acquired-record present but object not on this disk")

    import csv

    with raw_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        assert "block_id" in header and "base64_url" in header and "trip_id" in header
        block_index = header.index("block_id")
        populated = 0
        for row_number, row in enumerate(reader):
            if row_number >= 200_000:
                break
            if len(row) > block_index and row[block_index].strip():
                populated += 1
    assert populated > 0, (
        "no block_id value found in the first 200k trips -- the column exists but is "
        "empty, and every downstream figure would be a silent zero"
    )


def test_the_whole_ledger_still_loads_after_adding_seven_manifests() -> None:
    """Regression guard for the estate as a whole, not just this packet's rows."""
    manifests = sorted(_CATALOG.glob("*.manifest.json"))
    assert manifests, "the governance ledger is empty"
    for path in manifests:
        manifest = load_manifest(path)
        assert manifest.dataset_id == path.name[: -len(".manifest.json")], (
            f"{path.name}: filename and dataset_id disagree"
        )
