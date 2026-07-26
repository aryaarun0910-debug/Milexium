"""Bring `realdata/` under the estate's GOVERNANCE without moving a single file.

WHY THIS EXISTS
The repository has two data trees and they are not duplicates -- they have
different origins and, until now, different governance models:

  * `realdata/` -- the original product. Real panels, the five trained models,
    `train_real_models.py`, `leakage_audit.py`, the model cards. Hand-acquired,
    predating the estate discipline, with NO declared rights record.
  * `data/` -- the governed estate (blueprint 17, ADR-0013). Manifest-gated:
    rights MUST be declared, checksum verified, content-addressed promotion,
    MinIO-backed (ADR-0036).

The clutter is real, but the fix is NOT a file move. `realdata/` paths are
load-bearing:

  * the evidence registry pins panel paths AND their sha256 (52 hash pins), and
    those hashes had to be made cross-platform-stable via `.gitattributes` after
    CI caught a CRLF/LF mismatch -- moving files changes recorded provenance;
  * conformance tests read those exact paths (the forecast suite, the
    feature-store leakage proof on `aar_daily.csv`, the teardown demo on
    `raw_tlc/`);
  * nine ADRs cite them;
  * and `realdata/` is the founder's pre-expansion work, which the expansion is
    not meant to reorganise.

So the inconsistency worth closing is not "two folders". It is that `realdata/`
holds real TLC/MTA/Chicago data with NO declared rights, while `data/` refuses a
single byte without them. This script closes exactly that: it writes acquisition
manifests describing the `realdata/` sources, recording licence, commercial-use
position, provenance and retention, and pointing at their EXISTING paths.

WHAT THIS DELIBERATELY DOES NOT DO
It does not move, copy, re-download or checksum-promote anything, and it writes
no `.acquired.json` record -- these datasets were not acquired through
`app.estate.acquire`, and claiming otherwise would forge the very provenance
the estate exists to make trustworthy. The manifests carry
`already_present_at` in `derived_artifacts` so the catalog states plainly where
the bytes actually live and how they got there.

Usage:
  py -3 platform/tools/build_realdata_manifests.py          # write the manifests
  py -3 platform/tools/build_realdata_manifests.py --check  # verify, write nothing
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the repo root importable when run standalone (pytest sets this via
# pyproject's pythonpath; a bare `py -3 platform/tools/...` does not).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_REPO = Path(__file__).resolve().parents[2]
_CATALOG = _REPO / "data" / "catalog"

# Each entry describes a source ALREADY PRESENT under realdata/ or business/ntd/.
# `paths` are repo-relative and are recorded, never rewritten.
_SOURCES: list[dict] = [
    {
        "dataset_id": "realdata-nyc-aar-paratransit",
        "owner_and_source": (
            "New York City Transit / MTA, Access-A-Ride paratransit. Published via the MTA "
            "open-data programme and NYC Open Data. Acquired by hand into realdata/ before the "
            "governed estate (ADR-0013) existed; this manifest records the rights that were "
            "never written down, it does not re-acquire the data."
        ),
        "license_and_commercial_rights": (
            "NYC Open Data / MTA open data -- published for public use including commercial "
            "use, with no registration or API key. The MTA's open-data terms permit reuse and "
            "redistribution with attribution. NOTE: this is an AGGREGATE demand panel; no "
            "individual rider record is present or derivable."
        ),
        "decision_tasks_enabled": ["forecast.demand"],
        "geography": "New York City, by borough (the AAR service area).",
        "time_coverage": "daily and borough-hour panels, 2020-03 to 2025-01.",
        "source_url": "https://data.ny.gov/",
        "schema_and_format": (
            "CSV / gzipped CSV. realdata/panels/aar_daily.csv (daily scheduled trips) and "
            "realdata/panels/aar_hourly_borough.csv.gz (borough-hour demand)."
        ),
        "update_frequency": (
            "static snapshot -- these are committed panels, deliberately frozen so the model "
            "cards, the forecast leaderboard and the evidence registry stay reproducible."
        ),
        "canonical_contract": (
            "none-yet -- an aggregate demand panel, training and backtest input rather than a "
            "canonical entity. It is the target of the AAR booster in knowledge/docs/MODEL_CARDS.md."
        ),
        "acceptance_threshold": "non-empty; date column parses; no duplicate (date, borough) rows.",
        "retention_and_deletion": (
            "retained indefinitely as committed evidence -- the evidence registry pins these "
            "panels by sha256 and the forecast leaderboard traces values to them, so deleting "
            "them would break reproducibility rather than free space. Public aggregate data; "
            "no deletion obligation exists."
        ),
        "zone": "standards",
        "paths": [
            "realdata/panels/aar_daily.csv",
            "realdata/panels/aar_hourly_borough.csv.gz",
        ],
    },
    {
        "dataset_id": "realdata-nyc-tlc-trip-records",
        "owner_and_source": (
            "New York City Taxi & Limousine Commission (TLC) trip record data. Acquired by hand "
            "into realdata/raw_tlc/ and realdata/raw_tlc_taxi/ before the governed estate existed."
        ),
        "license_and_commercial_rights": (
            "NYC TLC publishes trip records as open data for public use, including commercial "
            "use, with no registration or key. Records are trip-level but contain NO rider "
            "identifier, name, or precise origin/destination address -- TLC publishes zone-level "
            "pickup/dropoff only."
        ),
        "decision_tasks_enabled": ["forecast.demand", "replay.deadhead_teardown"],
        "geography": "New York City, TLC taxi zones.",
        "time_coverage": "monthly Parquet files; FHVHV from 2019 onward, yellow/green longer.",
        "source_url": "https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page",
        "schema_and_format": (
            "Apache Parquet, one file per month per service. FHVHV carries request/on-scene/"
            "pickup/dropoff timestamps, which is what makes the ADR-0039 deadhead teardown "
            "possible on real public data."
        ),
        "update_frequency": "monthly upstream; the local copy is a static snapshot.",
        "canonical_contract": (
            "app.connect.tlc_trips maps these onto ServiceRequest (ADR-0011); "
            "app.replay.teardown consumes them as VehicleSegments (ADR-0039)."
        ),
        "acceptance_threshold": "parquet opens; expected timestamp columns present.",
        "retention_and_deletion": (
            "cheaply reproducible from the public source -- these raw files are gitignored and "
            "may be deleted to reclaim space (~57 GB) without losing evidence, since the "
            "committed artifacts derived from them carry their own hashes."
        ),
        "zone": "standards",
        "paths": ["realdata/raw_tlc/", "realdata/raw_tlc_taxi/"],
    },
    {
        "dataset_id": "realdata-mta-afc-ridership",
        "owner_and_source": (
            "Metropolitan Transportation Authority (MTA) automated fare collection ridership, "
            "bus and subway. Hand-acquired into realdata/panels/ before the estate existed."
        ),
        "license_and_commercial_rights": (
            "MTA open data, published for public use including commercial use, no key required. "
            "Aggregate ridership counts by route-hour and station-hour; no individual fare "
            "transaction or rider identifier is present."
        ),
        "decision_tasks_enabled": ["forecast.demand"],
        "geography": "New York City -- MTA bus routes and subway stations.",
        "time_coverage": "hourly panels, 2020-01 onward; monthly aggregates alongside.",
        "source_url": "https://data.ny.gov/",
        "schema_and_format": (
            "gzipped CSV. mta_subway_station_hour.csv.gz (~23.5M rows) and the bus route-hour "
            "equivalent, plus monthly rollups."
        ),
        "update_frequency": "static snapshot, frozen for reproducibility.",
        "canonical_contract": "none-yet -- aggregate demand panels feeding two of the four real models.",
        "acceptance_threshold": "non-empty; parses; no duplicate (unit, hour) rows.",
        "retention_and_deletion": (
            "retained as committed evidence; pinned by the evidence registry and the forecast "
            "leaderboard. Public aggregate data, no deletion obligation."
        ),
        "zone": "standards",
        "paths": [
            "realdata/panels/mta_subway_station_hour.csv.gz",
            "realdata/panels/mta_bus_monthly/",
            "realdata/panels/mta_subway_monthly/",
        ],
    },
    {
        "dataset_id": "realdata-chicago-tnp-trips",
        "owner_and_source": (
            "City of Chicago Data Portal, Transportation Network Provider (TNP) trips. "
            "Hand-acquired into realdata/panels/ before the estate existed."
        ),
        "license_and_commercial_rights": (
            "City of Chicago Data Portal open data -- public use including commercial use, no "
            "key required. Aggregated to community-area-hour here; the published source is "
            "already privacy-protected by the City (rounded times, census-tract geography)."
        ),
        "decision_tasks_enabled": ["forecast.demand"],
        "geography": "City of Chicago, by community area.",
        "time_coverage": "community-area-hour panel; monthly rollups 2018 onward.",
        "source_url": "https://data.cityofchicago.org/",
        "schema_and_format": "CSV / gzipped CSV, community-area-hour trip counts.",
        "update_frequency": "static snapshot, frozen for reproducibility.",
        "canonical_contract": "none-yet -- aggregate demand panel behind the Chicago model.",
        "acceptance_threshold": "non-empty; parses; community-area column present.",
        "retention_and_deletion": "retained as committed evidence; public aggregate data.",
        "zone": "standards",
        "paths": ["realdata/panels/chicago_monthly/"],
    },
    {
        "dataset_id": "realdata-ntd-agency-economics",
        "owner_and_source": (
            "Federal Transit Administration, National Transit Database -- the agency economics "
            "extract in business/ntd/agency_economics.csv, derived from published NTD annual tables."
        ),
        "license_and_commercial_rights": (
            "Public Domain U.S. Government work. NTD data is published by FTA for unrestricted "
            "public use including commercial use. Agency-level operating and service statistics; "
            "no personal data of any kind."
        ),
        "decision_tasks_enabled": ["forecast.demand", "outreach.peer_benchmark"],
        "geography": "United States, nationwide -- all NTD-reporting agencies.",
        "time_coverage": "report years 2022-2024; 2024 is the only year with full coverage.",
        "source_url": "https://www.transit.dot.gov/ntd",
        "schema_and_format": (
            "CSV, one row per agency per report year, with deadhead, opex, trips and derived "
            "per-trip and per-hour economics."
        ),
        "update_frequency": "annual upstream; local copy is a static snapshot.",
        "canonical_contract": (
            "none-yet -- an agency-year economics panel. Consumed by business/outreach/build_peer_insight.py "
            "for peer-relative benchmarking and by the NTD monthly model."
        ),
        "acceptance_threshold": "non-empty; ntd_id and report_year present; deadhead columns parse.",
        "retention_and_deletion": "retained as committed evidence; public-domain federal data.",
        "zone": "standards",
        "paths": ["business/ntd/agency_economics.csv"],
    },
]


def _manifest(src: dict) -> dict:
    """Build a manifest that describes an ALREADY-PRESENT source.

    Sizes are declared 0.0: these bytes are already on disk and were never routed
    through `acquire()`'s free-space guard, so quoting a download size would imply
    an acquisition that did not happen.
    """
    return {
        "dataset_id": src["dataset_id"],
        "owner_and_source": src["owner_and_source"],
        "license_and_commercial_rights": src["license_and_commercial_rights"],
        "decision_tasks_enabled": src["decision_tasks_enabled"],
        "geography": src["geography"],
        "time_coverage": src["time_coverage"],
        "source_url": src["source_url"],
        "expected_download_gb": 0.0,
        "expected_expanded_gb": 0.0,
        "expected_retained_gb": 0.0,
        "schema_and_format": src["schema_and_format"],
        "sensitive_fields": [],
        "update_frequency": src["update_frequency"],
        "source_checksum": None,
        "canonical_contract": src["canonical_contract"],
        "quality_tests": [],
        "acceptance_threshold": src["acceptance_threshold"],
        "retention_and_deletion": src["retention_and_deletion"],
        "derived_artifacts": [
            "GOVERNANCE-ONLY MANIFEST (platform/tools/build_realdata_manifests.py). These bytes were "
            "hand-acquired before the governed estate existed and live at the paths below. "
            "Nothing was moved, copied or re-downloaded, and NO .acquired.json record is "
            "written -- this dataset did not go through app.estate.acquire, and claiming "
            "it did would forge the provenance the estate exists to make trustworthy.",
            *(f"already_present_at: {p}" for p in src["paths"]),
        ],
        "zone": src["zone"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="verify only; write nothing")
    args = ap.parse_args()

    from app.estate.manifest import load_manifest

    _CATALOG.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    for src in _SOURCES:
        path = _CATALOG / f"{src['dataset_id']}.manifest.json"
        payload = json.dumps(_manifest(src), indent=2, sort_keys=True)

        if args.check:
            if not path.exists():
                problems.append(f"missing: {path.name}")
                continue
            if path.read_text(encoding="utf-8").strip() != payload.strip():
                problems.append(f"stale: {path.name}")
                continue
        else:
            path.write_text(payload, encoding="utf-8")

        try:
            load_manifest(path)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"invalid: {path.name}: {exc}")
            continue

        # every recorded path must actually exist -- a governance record pointing
        # at nothing is worse than none, because it looks like coverage
        for rel in src["paths"]:
            if not (_REPO / rel).exists():
                problems.append(f"{src['dataset_id']}: recorded path missing: {rel}")

        if not args.check:
            print(f"wrote {path.relative_to(_REPO)}")

    if problems:
        print("\nPROBLEMS:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    print(f"\n{len(_SOURCES)} realdata/ntd sources now carry a governance manifest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
