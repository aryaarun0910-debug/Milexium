"""Forecast-leaderboard conformance (Phase-2 item 3).

Proves the leaderboard artifact is a faithful, third-party-checkable projection
of the committed metrics files rather than a hand-copied summary:

1. The generator runs and produces BOTH files (json + md).
2. Every leaderboard value is traceable: for each row, re-read the source JSON
   at the exact `json_path` the artifact cites and assert the value matches --
   so no cell is a transcribed number.
3. The seasonal-naive baseline is present (and non-null) for EVERY model row and
   for every metric on it -- the repo's "no number ships without its naive"
   discipline, enforced.
4. Derived fields (`model_beats_naive`, `improvement_abs`) are recomputed from
   the raw source values and must agree.
5. The excluded kaggle transformer is NOT a row, and its cited source really
   carries the number the exclusion claims.

Skips cleanly if `realdata/metrics_real.json` is absent (nothing to package).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_METRICS_REAL = _REPO_ROOT / "realdata" / "metrics_real.json"
_GENERATOR = _REPO_ROOT / "benchmarks" / "quality" / "build_forecast_leaderboard.py"
_JSON_OUT = _REPO_ROOT / "benchmarks" / "quality" / "forecast_leaderboard.json"
_MD_OUT = _REPO_ROOT / "benchmarks" / "quality" / "forecast_leaderboard.md"

pytestmark = pytest.mark.skipif(
    not _METRICS_REAL.exists(),
    reason="realdata/metrics_real.json absent -- nothing to build a forecast leaderboard from",
)


def _resolve_json_path(doc: dict, json_path: str):
    """Resolve the small JSON-path dialect the artifact emits: '$', dotted keys,
    and bracket-quoted keys for names containing special characters, e.g.
    '$.temporal.model_r2' or "$.['daily+hourly'].model_r2"."""
    assert json_path.startswith("$"), json_path
    rest = json_path[1:]
    node = doc
    i = 0
    while i < len(rest):
        ch = rest[i]
        if ch == ".":
            i += 1
            continue
        if ch == "[":
            close = rest.index("]", i)
            token = rest[i + 1:close].strip()
            if token[0] in "'\"":
                token = token[1:-1]
            node = node[token]
            i = close + 1
        else:
            j = i
            while j < len(rest) and rest[j] not in ".[":
                j += 1
            node = node[rest[i:j]]
            i = j
    return node


@pytest.fixture(scope="module")
def leaderboard() -> dict:
    """Run the real generator as a subprocess (proving it runs end-to-end), then
    load the JSON it wrote."""
    result = subprocess.run(
        [sys.executable, str(_GENERATOR)],
        capture_output=True, text=True, cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, f"generator failed:\n{result.stdout}\n{result.stderr}"
    assert _JSON_OUT.exists(), "generator did not write forecast_leaderboard.json"
    assert _MD_OUT.exists(), "generator did not write forecast_leaderboard.md"
    return json.loads(_JSON_OUT.read_text(encoding="utf-8"))


def test_generator_produces_both_files(leaderboard: dict) -> None:
    assert leaderboard["artifact"] == "forecast_leaderboard"
    assert leaderboard["rows"], "leaderboard has no model rows"
    md = _MD_OUT.read_text(encoding="utf-8")
    assert "Forecast demand leaderboard" in md
    assert "seasonal-naive" in md


def test_every_row_has_the_expected_shape(leaderboard: dict) -> None:
    # The four zone-hour models must be present (product target + 3 generalization).
    keys = {r["model_key"] for r in leaderboard["rows"]}
    assert {"nyc_access_a_ride", "chicago_tnp", "mta_bus", "mta_subway"} <= keys
    for r in leaderboard["rows"]:
        assert r["task"] == "forecast.demand"
        assert r["spatial_grain"] and r["temporal_grain"]
        assert r["evaluation_window"]
        assert r["headline_metric"] in r["metrics"]
        assert r["metrics"], "row has no metrics"


def test_every_value_traces_to_its_cited_source(leaderboard: dict) -> None:
    """The core traceability property: re-read each cited source JSON at the
    cited json_path and assert every model AND naive value matches exactly.
    Re-reading (not trusting the artifact) is what proves nothing was hand-copied."""
    doc_cache: dict[str, dict] = {}

    def load(rel_file: str) -> dict:
        if rel_file not in doc_cache:
            doc_cache[rel_file] = json.loads((_REPO_ROOT / rel_file).read_text(encoding="utf-8"))
        return doc_cache[rel_file]

    for r in leaderboard["rows"]:
        # The evaluation window is itself sourced -- verify it too.
        ews = r["evaluation_window_source"]
        assert _resolve_json_path(load(ews["file"]), ews["json_path"]) == r["evaluation_window"]

        for name, cell in r["metrics"].items():
            model_src = cell["model_source"]
            naive_src = cell["naive_source"]
            model_from_source = _resolve_json_path(load(model_src["file"]), model_src["json_path"])
            naive_from_source = _resolve_json_path(load(naive_src["file"]), naive_src["json_path"])
            assert model_from_source == cell["model"], (
                f"{r['model_key']}.{name}: artifact model={cell['model']} but "
                f"{model_src['file']}{model_src['json_path']}={model_from_source}"
            )
            assert naive_from_source == cell["naive"], (
                f"{r['model_key']}.{name}: artifact naive={cell['naive']} but "
                f"{naive_src['file']}{naive_src['json_path']}={naive_from_source}"
            )


def test_naive_baseline_present_for_every_model_and_metric(leaderboard: dict) -> None:
    """The repo discipline: no number ships without its seasonal-naive comparison."""
    for r in leaderboard["rows"]:
        for name, cell in r["metrics"].items():
            assert cell["naive"] is not None, f"{r['model_key']}.{name} missing naive baseline"
            assert isinstance(cell["naive"], (int, float))
            assert cell["model"] is not None


def test_derived_beats_and_improvement_are_consistent(leaderboard: dict) -> None:
    """model_beats_naive and improvement_abs must follow from the raw values and
    the stated direction -- not be asserted independently of them."""
    for r in leaderboard["rows"]:
        for name, cell in r["metrics"].items():
            model, naive = cell["model"], cell["naive"]
            if cell["higher_is_better"]:
                assert cell["model_beats_naive"] == (model > naive), f"{r['model_key']}.{name}"
                assert cell["improvement_abs"] == pytest.approx(model - naive, abs=1e-6)
            else:
                assert cell["model_beats_naive"] == (model < naive), f"{r['model_key']}.{name}"
                assert cell["improvement_abs"] == pytest.approx(naive - model, abs=1e-6)
        # The row-level headline flag mirrors its headline metric cell.
        headline = r["metrics"][r["headline_metric"]]
        assert r["beats_naive_on_headline"] == headline["model_beats_naive"]


def test_at_least_one_row_honestly_does_not_beat_naive(leaderboard: dict) -> None:
    """The NTD temporal split loses to naive on R2; the artifact must surface it
    rather than hide it. This guards against a future silent drop of the honest
    negative result."""
    temporal = [r for r in leaderboard["rows"] if r["model_key"] == "ntd_monthly.temporal"]
    if temporal:  # NTD file is optional; only assert if the row was built
        assert temporal[0]["beats_naive_on_headline"] is False
    # And the dedicated honesty section is non-empty and each finding is sourced.
    findings = leaderboard["does_not_beat_naive"]
    assert findings, "expected at least one honest does-not-beat-naive finding"
    for f in findings:
        if "source" in f:
            assert (_REPO_ROOT / f["source"]["file"]).exists()
        else:
            for v in f["values"].values():
                got = _resolve_json_path(
                    json.loads((_REPO_ROOT / v["source"]["file"]).read_text(encoding="utf-8")),
                    v["source"]["json_path"],
                )
                assert got == v["value"]


def test_excluded_transformer_is_not_a_row_and_its_claim_is_sourced(leaderboard: dict) -> None:
    """The kaggle transformer must NOT be a production row, mirroring
    MODEL_CARDS.md 'Not shipped' -- and the number the exclusion cites must
    really live at the cited source (0.933, the value it lost with)."""
    keys = {r["model_key"] for r in leaderboard["rows"]}
    assert not any("transformer" in k or "kaggle" in k for k in keys)

    excluded = leaderboard["excluded"]
    assert excluded, "expected the transformer to be recorded as excluded"
    transformer = excluded[0]
    src = transformer["source"]
    src_path = _REPO_ROOT / src["file"]
    if src_path.exists():  # committed kaggle results
        value = _resolve_json_path(json.loads(src_path.read_text(encoding="utf-8")), src["json_path"])
        assert value == 0.933, f"exclusion cites 0.933 but source has {value}"
