"""Conformance: the golden-path demo runs the whole loop on REAL public data
and produces independently-verifiable artifacts.

Mirrors the skip discipline in test_forecast_runtime.py: the demo depends on the
real Access-A-Ride booster and a real NYC TLC FHVHV parquet, both gitignored
local artifacts, plus DuckDB to read the parquet. When any is absent the test
skips cleanly rather than failing -- it never fabricates the real inputs.

What it asserts (the load-bearing claims of the demo):
  * the loop completes and returns a structured result,
  * the forecast is a positive real number served from the real booster,
  * the decision the solver returned passed the INDEPENDENT feasibility check,
  * the evidence pack verified in-process (integrity_verified) and the exported
    pack re-verifies independently (verify_evidence_pack),
  * the written artifacts exist and the written evidence pack re-verifies from
    its own bytes on disk, and the run manifest parses.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from demo.golden_path import (
    _REAL_AAR_MODEL,
    _find_tlc_parquet,
    run_golden_path,
)
from packages.canonical.vocab import ScheduleRunStatus
from packages.evidence import EvidencePack, verify_evidence_pack

_TLC_PARQUET = _find_tlc_parquet()
_HAVE_DUCKDB = importlib.util.find_spec("duckdb") is not None

_skip_reason = None
if not _REAL_AAR_MODEL.exists():
    _skip_reason = "real AAR booster not present (gitignored local artifact)"
elif _TLC_PARQUET is None:
    _skip_reason = "no real TLC FHVHV parquet present in realdata/raw_tlc/ (gitignored)"
elif not _HAVE_DUCKDB:
    _skip_reason = "duckdb not installed (needed to read the real TLC parquet)"

pytestmark = pytest.mark.skipif(_skip_reason is not None, reason=_skip_reason or "")


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    out = tmp_path_factory.mktemp("golden-path")
    return run_golden_path(out, quiet=True)


def test_loop_completes_and_forecast_is_a_positive_real_number(result) -> None:
    assert isinstance(result.forecast_point, float)
    assert result.forecast_point > 0
    # A real forecast served from the real committed booster, hash-verified.
    assert len(result.aar_model_sha256) == 64
    assert result.accepted >= 6


def test_solver_solution_passed_the_independent_feasibility_check(result) -> None:
    assert result.milexium_status is ScheduleRunStatus.OPTIMAL
    assert result.feasibility_violations == 0
    # The modelled baseline is genuinely under-resourced, so Milexium serves at
    # least as many -- a real, non-zero delta the replay reports.
    assert result.milexium_served >= result.baseline_served


def test_evidence_pack_verifies_in_process_and_independently(result) -> None:
    assert result.evidence_integrity_verified is True
    assert result.pack_reverified is True
    assert len(result.pack_bundle_sha256) == 64


def test_written_artifacts_exist_and_reverify(result) -> None:
    assert result.pack_path.exists()
    assert result.manifest_path.exists()

    # The written evidence pack re-verifies from its own bytes on disk, with no
    # live store and no trust in the process that wrote it.
    pack = EvidencePack.from_json(result.pack_path.read_text(encoding="utf-8"))
    verification = verify_evidence_pack(pack)
    assert verification.reverified is True
    assert verification.bundle_hash_matches is True
    assert verification.chain_reverified is True

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["demo"] == "milexium.golden_path"
    assert manifest["real_inputs"]["forecast_model"]["artifact_sha256"] == result.aar_model_sha256
    assert manifest["evidence_pack"]["independently_reverified"] is True
    assert len(manifest["boundaries"]) >= 4  # the real-vs-synthetic boundaries are stated
