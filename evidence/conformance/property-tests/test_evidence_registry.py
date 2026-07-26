"""Conformance for the machine-readable evidence registry (Phase-2 item 4).

The registry is the anti-overclaim tool: it maps every public claim to a
traceable source, a dataset manifest with a recorded sha256, an evaluation
window, a status label from the fixed vocabulary, and a plain-language
limitation. These tests prove the generator produces such a registry and that
its verifier actually verifies -- i.e. it stays clean on a good registry and
flags a bad one.

Skips cleanly when the primary evidence sources are absent (a fresh checkout
without the committed metrics/manifests is not a failure here).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.build_evidence_registry import (
    STATUS_VOCAB,
    build_registry,
    render_readme,
    verify_evidence_registry,
    write_registry,
)

ROOT = Path(__file__).resolve().parents[3]

# The registry needs at least the real metrics + manifests to be meaningful.
_PRIMARY = ROOT / "realdata" / "metrics_real.json"
_MANIFESTS = ROOT / "realdata" / "manifests"
_needs_sources = pytest.mark.skipif(
    not (_PRIMARY.exists() and _MANIFESTS.exists()),
    reason="committed evidence sources (realdata/metrics_real.json + manifests) absent",
)


@pytest.fixture(scope="module")
def registry() -> dict:
    return build_registry(ROOT)


# --- generator produces a well-formed registry ----------------------------- #

@_needs_sources
def test_generator_produces_registry(registry: dict) -> None:
    assert registry["schema"] == "milexium-evidence-registry/v1"
    assert registry["canonical_contract_version"]  # non-empty
    assert registry["status_vocabulary"] == list(STATUS_VOCAB)
    assert len(registry["claims"]) > 0
    assert len(registry["manifests"]) > 0
    # Every emitted number is traceable: each claim names at least one source
    # file, a status in the fixed vocabulary, and a non-empty limitation.
    for c in registry["claims"]:
        assert c["source_files"], f"{c['id']} has no source"
        assert c["status"] in STATUS_VOCAB
        assert c["limitation"].strip()


@_needs_sources
def test_registry_indexes_the_expected_evidence(registry: dict) -> None:
    ids = {c["id"] for c in registry["claims"]}
    # forecast headline (AAR is the product target) and its naive baseline
    assert "forecast.nyc_access_a_ride.model_r2" in ids
    aar = next(c for c in registry["claims"] if c["id"] == "forecast.nyc_access_a_ride.model_r2")
    assert aar["value"] == 0.9857
    assert aar["baseline"]["value"] == 0.9231
    assert aar["dataset_sha256"]  # ties the claim to a provenance manifest
    # the DARP benchmark, the leakage verdict, and the contract version
    assert any(i.startswith("darp.") for i in ids)
    assert "leakage.overall" in ids
    assert "canonical.contract_version" in ids


# --- the verifier is clean on a good registry ------------------------------ #

@_needs_sources
def test_verifier_clean_on_generated_registry(registry: dict) -> None:
    assert verify_evidence_registry(registry, ROOT) == []


@_needs_sources
def test_written_registry_roundtrips_and_verifies(tmp_path: Path, registry: dict) -> None:
    reg_path, readme_path = write_registry(registry, tmp_path)
    assert reg_path.exists() and readme_path.exists()
    reloaded = json.loads(reg_path.read_text(encoding="utf-8"))
    assert verify_evidence_registry(reloaded, ROOT) == []
    # the human index renders and names the anti-overclaim purpose
    md = render_readme(registry)
    assert "Evidence registry" in md and "limitation" in md


# --- the verifier FLAGS a broken registry ---------------------------------- #

@_needs_sources
def test_verifier_flags_missing_source(registry: dict) -> None:
    broken = copy.deepcopy(registry)
    broken["claims"][0]["source_files"] = ["realdata/does_not_exist_zzz.json"]
    problems = verify_evidence_registry(broken, ROOT)
    assert any("source file missing" in p for p in problems)


@_needs_sources
def test_verifier_flags_untraceable_claim(registry: dict) -> None:
    broken = copy.deepcopy(registry)
    broken["claims"][0]["source_files"] = []
    problems = verify_evidence_registry(broken, ROOT)
    assert any("no source_files" in p or "untraceable" in p for p in problems)


@_needs_sources
def test_verifier_flags_missing_limitation(registry: dict) -> None:
    broken = copy.deepcopy(registry)
    broken["claims"][0]["limitation"] = "   "
    problems = verify_evidence_registry(broken, ROOT)
    assert any("limitation" in p for p in problems)


@_needs_sources
def test_verifier_flags_bad_status(registry: dict) -> None:
    broken = copy.deepcopy(registry)
    broken["claims"][0]["status"] = "TotallyProven"
    problems = verify_evidence_registry(broken, ROOT)
    assert any("vocabulary" in p for p in problems)


@_needs_sources
def test_verifier_flags_sha256_mismatch(registry: dict) -> None:
    broken = copy.deepcopy(registry)
    # find a claim with a recomputable content check (a present local panel)
    target = None
    for c in broken["claims"]:
        for cc in c.get("content_checks", []):
            if (ROOT / cc["path"]).exists():
                cc["sha256"] = "0" * 64
                target = c["id"]
                break
        if target:
            break
    if target is None:
        pytest.skip("no present local panel file to corrupt a checksum against")
    problems = verify_evidence_registry(broken, ROOT)
    assert any("sha256 mismatch" in p for p in problems)
