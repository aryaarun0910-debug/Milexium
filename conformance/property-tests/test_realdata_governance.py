"""Every real dataset in this repository declares its rights (ADR-0053).

The repo has two data trees with different origins: `realdata/` (the original
product, hand-acquired before the estate discipline existed) and `data/` (the
governed estate, which refuses a byte without declared rights). The gap worth
closing was never "two folders" -- it was that one tree held real TLC/MTA/Chicago
data with NO rights record while the other refused to.

These tests hold that closed. They deliberately do NOT assert anything about
file LOCATION: `realdata/` paths are pinned by sha256 in the evidence registry
and read directly by the forecast, leakage and teardown suites, so moving them
would break recorded provenance to buy tidiness.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.estate.manifest import load_manifest

_REPO = Path(__file__).resolve().parents[2]
_CATALOG = _REPO / "data" / "catalog"
_REALDATA_MANIFESTS = sorted(_CATALOG.glob("realdata-*.manifest.json"))

_PLACEHOLDERS = ("tbd", "unknown", "todo", "change-me", "n/a", "?")


def test_the_realdata_governance_manifests_exist() -> None:
    """If this fails, tools/build_realdata_manifests.py has not been run."""
    assert _REALDATA_MANIFESTS, "no realdata-* governance manifests found"


@pytest.mark.parametrize("path", _REALDATA_MANIFESTS, ids=lambda p: p.stem)
def test_each_manifest_loads_and_declares_real_rights(path: Path) -> None:
    """`load_manifest` enforces the schema; this adds the check it cannot make --
    that the rights field says something, rather than parking a placeholder."""
    manifest = load_manifest(path)

    rights = manifest.license_and_commercial_rights.strip()
    assert len(rights) > 40, f"{path.stem}: rights text is too thin to be a real declaration"
    assert not any(p in rights.lower() for p in _PLACEHOLDERS), (
        f"{path.stem}: rights field contains a placeholder"
    )
    # commercial position must be addressed explicitly -- it is the question a
    # reviewer actually asks, and silence reads as "nobody checked"
    assert "commercial" in rights.lower()


@pytest.mark.parametrize("path", _REALDATA_MANIFESTS, ids=lambda p: p.stem)
def test_each_manifest_points_at_paths_that_actually_exist(path: Path) -> None:
    """A governance record pointing at nothing is worse than none, because it
    looks like coverage. Every `already_present_at` path must resolve."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    recorded = [
        line.split("already_present_at:", 1)[1].strip()
        for line in payload.get("derived_artifacts", [])
        if isinstance(line, str) and line.startswith("already_present_at:")
    ]
    assert recorded, f"{path.stem}: records no path"
    for rel in recorded:
        assert (_REPO / rel).exists(), f"{path.stem}: recorded path does not exist: {rel}"


@pytest.mark.parametrize("path", _REALDATA_MANIFESTS, ids=lambda p: p.stem)
def test_no_acquired_record_is_forged_for_a_hand_acquired_dataset(path: Path) -> None:
    """These datasets did NOT go through packages.estate.acquire.

    An `.acquired.json` beside them would assert a free-space guard, a quarantine
    step and a checksum-verified promotion that never happened -- forging exactly
    the provenance the estate exists to make trustworthy. The manifest describes
    rights; it must not imply an acquisition.
    """
    acquired = _CATALOG / f"{path.stem.replace('.manifest', '')}.acquired.json"
    assert not acquired.exists(), (
        f"{acquired.name} exists -- that would claim an acquisition through the "
        "governed pipeline which never took place"
    )
