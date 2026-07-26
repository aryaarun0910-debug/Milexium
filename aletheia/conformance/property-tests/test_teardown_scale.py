"""The teardown scale benchmark harness itself (aletheia/benchmarks/performance/teardown_scale.py).

These tests assert the HARNESS is correct, not that the teardown is fast. They
run it at a deliberately tiny size and check that the artifact it produces is
well-formed and honest. The multi-million-segment ladder is NOT run here: a test
suite that takes twenty minutes stops being run, and a benchmark's job is to be
re-runnable on demand, not on every commit.

What "honest" means concretely, and is asserted below:

- A measurement is labelled with the machine that produced it. A wall-clock
  number without its CPU, RAM and Python version is not reproducible, so the
  artifact is required to carry them.
- A rung that fails is recorded as a rung that failed, with a status naming why.
  The ladder's stopping point is a result -- it must never be silently dropped,
  leaving the artifact looking like a clean sweep.
- The per-segment memory figure is a marginal slope across rungs, never
  `peak_rss / segments`: each child carries a fixed ~60-200 MB interpreter and
  DuckDB cost that has nothing to do with the input.
- The benchmark measures `teardown_deadhead` unmodified. If the module's private
  stage helpers are renamed, the stage attribution silently becomes wrong, so
  their existence is pinned here rather than discovered in a stale artifact.

The real TLC corpus (`data/curated/raw_tlc/`, ~37 GB) is gitignored, so every test
that needs input data skips cleanly when it is absent and CI stays green.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BENCH_DIR = _REPO_ROOT / "aletheia" / "benchmarks" / "performance"
if str(_BENCH_DIR) not in sys.path:
    sys.path.insert(0, str(_BENCH_DIR))

import teardown_scale as bench  # noqa: E402

# Small enough that the whole harness -- subprocess spawn, DuckDB scan, three
# measurement passes and a cProfile pass -- finishes in seconds.
TINY_RUNG = 400


def _require_corpus() -> list[Path]:
    files = bench.source_files(bench._DEFAULT_SOURCE)
    if not files:
        pytest.skip(f"no {bench._DEFAULT_SOURCE} under {bench._RAW_TLC} (gitignored corpus)")
    pytest.importorskip("duckdb")
    return files


# --------------------------------------------------------------------------
# The harness runs, end to end, and writes a well-formed artifact
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tiny_run(tmp_path_factory) -> dict:
    """One real end-to-end run of the harness at a tiny rung, shared by the
    artifact assertions so the subprocess cost is paid once."""
    _require_corpus()
    out_dir = tmp_path_factory.mktemp("teardown_scale")
    code = bench.main(
        ["--rungs", f"{TINY_RUNG // 2},{TINY_RUNG}", "--repeats", "2", "--out-dir", str(out_dir)]
    )
    assert code == 0
    return {
        "dir": out_dir,
        "payload": json.loads((out_dir / "teardown_scale_results.json").read_text(encoding="utf-8")),
        "markdown": (out_dir / "teardown_scale.md").read_text(encoding="utf-8"),
    }


def test_the_harness_produces_both_artifacts_and_every_rung_reports_a_status(tiny_run) -> None:
    assert (tiny_run["dir"] / "teardown_scale_results.json").is_file()
    assert (tiny_run["dir"] / "teardown_scale.md").is_file()

    results = tiny_run["payload"]["results"]
    assert len(results) == 2
    # Every requested rung appears with a status. A rung that fell over must be
    # visible as a failed rung; dropping it would make the ladder look complete.
    for record in results:
        assert record["status"], "a rung with no status is a rung that cannot be judged"
        assert record["target_segments"] in {TINY_RUNG // 2, TINY_RUNG}
    assert [r["target_segments"] for r in results] == tiny_run["payload"]["meta"]["rungs_requested"]


def test_a_measurement_carries_the_machine_that_produced_it(tiny_run) -> None:
    """A benchmark without its hardware is not reproducible."""
    machine = tiny_run["payload"]["meta"]["machine"]
    assert machine["python_version"].startswith(f"{sys.version_info.major}.")
    assert machine["platform"]
    assert machine["machine"]
    # RAM/core counts come from psutil, which is NOT a declared dependency: the
    # keys are always present, the values are allowed to be None without it.
    for key in ("cpu_cores_logical", "ram_total_bytes", "ram_available_bytes_at_start"):
        assert key in machine

    text = tiny_run["markdown"]
    assert "## Machine" in text
    assert machine["python_version"] in text


def test_a_successful_rung_reports_time_memory_and_a_verifiable_input(tiny_run) -> None:
    done = [r for r in tiny_run["payload"]["results"] if r["status"] == "ok"]
    assert done, "the tiny ladder should complete; a failure here is a harness bug"

    for record in done:
        assert record["segments"] == record["target_segments"]
        assert record["timing"]["wall_s_median"] > 0
        assert record["timing"]["repeats"] == 2
        assert len(record["timing"]["wall_s_all"]) == 2
        assert record["us_per_segment"] > 0
        assert record["memory"]["tracemalloc_teardown_extra_bytes"] > 0

        # The input this timing describes is identifiable, so the run is a
        # measurement of something specific rather than an unattributable duration.
        facts = record["result_facts"]
        assert len(facts["teardown_id"]) == 64
        assert len(facts["segment_sha256"]) == 64
        assert facts["total_deadhead_minutes"] > 0
        assert 0.0 < facts["deadhead_share_of_vehicle_time"] < 1.0


def test_stage_attribution_covers_the_call_it_claims_to_explain(tiny_run) -> None:
    """The stage timers and the timed full call are separate passes, so they
    agree to within noise, not exactly. The harness must report that agreement
    -- an attribution that only accounts for a third of the runtime is not an
    explanation of where the time goes."""
    done = [r for r in tiny_run["payload"]["results"] if r["status"] == "ok"]
    for record in done:
        stages = record["stages_s"]
        named = {k: v for k, v in stages.items() if not k.startswith("_")}
        assert "hour_boundary_split" in named
        assert "fingerprint_sha256" in named
        assert "run_grouping" in named
        assert stages["_stage_total"] == pytest.approx(sum(named.values()), abs=1e-3)

        agreement = record["stage_total_vs_wall"]
        # Coverage is REPORTED and sanity-bounded, not gated on a floor.
        #
        # It is the ratio of two independently-timed passes over the same work,
        # so it measures the machine as much as the code: this assertion was
        # originally `> 50.0` and read 40.7 while an unrelated PostgreSQL suite
        # ran concurrently, then passed on the same commit when run alone. A
        # test that is green on an idle laptop and red on a loaded CI runner
        # tells you about the runner, and spends the suite's credibility to do
        # it -- the failure it produces is indistinguishable from a real one.
        #
        # What survives is the half that cannot be moved by load. An upper
        # bound still catches the defect that matters here: stage timers that
        # double-count would make the parts sum to more than the whole, and no
        # amount of contention can inflate stage_total past wall time. The
        # low-coverage question the docstring raises is a property of the
        # benchmark run, so it is answered in teardown_scale.md, where the
        # number can be reread and re-run rather than silently gating CI.
        assert agreement["stage_coverage_pct"] > 0.0
        assert agreement["stage_coverage_pct"] < 150.0
        # The difference is reported signed. Clamping it at zero would hide a
        # stage pass that overshoots and pass off noise as a real residual.
        assert agreement["difference_s"] == pytest.approx(
            agreement["wall_s_median"] - agreement["stage_total_s"], abs=1e-3
        )


def test_the_markdown_states_a_verdict_and_its_limitations(tiny_run) -> None:
    text = tiny_run["markdown"]
    assert "## Verdict" in text
    assert "## Honest limitations" in text
    assert "ADR-0026" in text
    # Whatever the verdict is, the trigger it decides must be named explicitly
    # rather than left for a reader to infer.
    assert "trigger" in text.lower()
    # Projections beyond what was measured are labelled as projections.
    assert "PROJECTION" in text or "projection" in text.lower()
    assert "Sample, not census" in text


# --------------------------------------------------------------------------
# The derived figures are derived correctly
# --------------------------------------------------------------------------


def _mem_rung(segments: int, resident: int, heap: int, peak: int) -> dict:
    return {
        "status": "ok",
        "segments": segments,
        "rss_bytes_with_segments": resident,
        "peak_rss_bytes": peak,
        "memory": {"tracemalloc_teardown_extra_bytes": heap},
    }


def test_memory_per_segment_is_a_marginal_slope_not_peak_over_count() -> None:
    """`peak_rss / segments` would charge every segment a share of the fixed
    interpreter cost. On these rungs that naive figure is ~21 kB/segment at the
    small rung and ~5 kB at the large one -- an "law" that changes with input
    size is not a law. The marginal slope is a flat 1 kB either way."""
    records = [
        _mem_rung(10_000, 100_000_000 + 6_000_000, 4_000_000, 200_000_000 + 10_000_000),
        _mem_rung(50_000, 100_000_000 + 30_000_000, 20_000_000, 200_000_000 + 50_000_000),
    ]
    slope = bench.memory_slope(records)
    assert slope["peak_rss_bytes_per_segment"] == pytest.approx(1000.0, rel=1e-6)
    assert slope["peak_rss_fixed_overhead_bytes"] == pytest.approx(200_000_000, rel=1e-6)
    assert slope["resident_bytes_per_segment"] == pytest.approx(600.0, rel=1e-6)
    assert slope["fitted_over_segments"] == [10_000, 50_000]


def test_the_heap_figure_is_measured_per_rung_not_fitted() -> None:
    """tracemalloc counts allocations, so it survives the OS trimming a working
    set. Reporting it per rung (with its spread) means a reader can see the
    linearity in the raw numbers instead of trusting a fitted line."""
    records = [
        _mem_rung(10_000, 106_000_000, 5_000_000, 210_000_000),
        _mem_rung(50_000, 130_000_000, 26_000_000, 250_000_000),
    ]
    slope = bench.memory_slope(records)
    assert slope["heap_bytes_per_segment"] == pytest.approx(510.0)
    assert slope["heap_bytes_per_segment_min"] == pytest.approx(500.0)
    assert slope["heap_bytes_per_segment_max"] == pytest.approx(520.0)
    # Holding the segments plus the transient heap is what a machine must fit.
    assert slope["total_bytes_per_segment"] == pytest.approx(
        slope["heap_bytes_per_segment"] + slope["resident_bytes_per_segment"]
    )


def test_a_peak_rss_below_measured_demand_is_flagged_not_believed() -> None:
    """Peak working set stops tracking demand once the OS starts paging. A peak
    below (resident segments + measured heap peak) is arithmetically impossible
    without trimming, so the harness names that rung instead of letting an
    under-reported peak flatten the memory curve."""
    honest = _mem_rung(10_000, 100_000_000, 10_000_000, 150_000_000)
    trimmed = _mem_rung(50_000, 500_000_000, 50_000_000, 400_000_000)
    slope = bench.memory_slope([honest, trimmed])
    assert slope["rungs_where_peak_rss_understates_demand"] == [50_000]

    clean = bench.memory_slope(
        [honest, _mem_rung(50_000, 500_000_000, 50_000_000, 600_000_000)]
    )
    assert clean["rungs_where_peak_rss_understates_demand"] == []


def test_memory_slope_refuses_to_fit_a_line_through_one_point() -> None:
    assert bench.memory_slope([]) is None
    assert bench.memory_slope([_mem_rung(10, 1, 1, 1)]) is None
    # A rung that failed carries no measurements, so it cannot anchor a slope.
    assert (
        bench.memory_slope([_mem_rung(10, 1, 1, 1), {"status": "child_died", "target_segments": 20}])
        is None
    )


def test_the_scaling_exponent_names_the_shape_of_the_curve() -> None:
    """10x input for 10x time is slope 1; 10x for 100x is slope 2. The harness
    reports the number so the shape is read off a measurement, not asserted."""
    linear = bench.scaling_exponents(
        [
            {"status": "ok", "segments": 100_000, "timing": {"wall_s_median": 1.0}},
            {"status": "ok", "segments": 1_000_000, "timing": {"wall_s_median": 10.0}},
        ]
    )
    assert linear[0]["log_log_slope"] == pytest.approx(1.0, abs=1e-3)
    assert linear[0]["input_ratio"] == pytest.approx(10.0)

    quadratic = bench.scaling_exponents(
        [
            {"status": "ok", "segments": 100_000, "timing": {"wall_s_median": 1.0}},
            {"status": "ok", "segments": 1_000_000, "timing": {"wall_s_median": 100.0}},
        ]
    )
    assert quadratic[0]["log_log_slope"] == pytest.approx(2.0, abs=1e-3)


def test_a_failed_rung_never_becomes_a_data_point() -> None:
    """A rung that ran out of memory must not be interpolated over: the curve
    would then be drawn through a point that was never measured."""
    records = [
        {"status": "ok", "segments": 100_000, "timing": {"wall_s_median": 1.0}},
        {"status": "memory_limit_during_teardown", "target_segments": 1_000_000},
        {"status": "ok", "segments": 2_000_000, "timing": {"wall_s_median": 25.0}},
    ]
    slopes = bench.scaling_exponents(records)
    assert [(s["from_segments"], s["to_segments"]) for s in slopes] == [(100_000, 2_000_000)]


# --------------------------------------------------------------------------
# The harness is measuring the shipped code, and degrades honestly
# --------------------------------------------------------------------------


def test_the_stage_helpers_the_attribution_depends_on_still_exist() -> None:
    """Stage attribution is white-box: it calls teardown.py's private helpers.
    If those are renamed the artifact's "where the time goes" table becomes
    wrong while still looking plausible, so the coupling is pinned here."""
    from aletheia.replay import teardown as module

    for name in ("_atoms", "_buckets", "_run_contributions", "_hour_slices"):
        assert callable(getattr(module, name)), f"teardown.py::{name} moved; stage table is stale"
    assert callable(module.segment_set_fingerprint)
    assert callable(module.teardown_deadhead)


def test_the_benchmark_calls_the_teardown_unmodified() -> None:
    """It measures the shipped function with the shipped cost path -- no
    benchmark-only fast path, no tuned parameters."""
    assert bench.teardown_deadhead.__module__ == "aletheia.replay.teardown"
    assert bench._TEARDOWN_KWARGS["data_provenance"] == "real_public"
    assert bench._TEARDOWN_KWARGS["cost_basis"] is not None
    # The stand-in rate is labelled a stand-in wherever it appears.
    assert "STAND-IN" in bench._TEARDOWN_KWARGS["cost_basis"].source


def test_segments_are_derived_the_way_adr_0039_derives_them() -> None:
    """request -> on_scene is the empty approach; pickup -> dropoff the revenue
    leg; the curb wait is excluded. If the benchmark invented a different
    segmentation its numbers would not describe the shipped analysis."""
    files = _require_corpus()
    built = bench.build_segments(files, target=200)
    segments = built["segments"]

    assert len(segments) == 200
    assert built["rows_read"] > 0
    assert built["reached_target"] is True
    kinds = {s.kind for s in segments}
    assert kinds == {"revenue", "deadhead"}
    # Rows publishing no on-scene timestamp are counted, never imputed as zero
    # empty time (ADR-0039's 32.6% finding).
    assert built["unmeasured_rows"] > 0
    assert all(s.ended_at >= s.started_at for s in segments)
    assert all(s.run_ref is None or s.run_ref.strip() == s.run_ref for s in segments)


def test_the_harness_exits_zero_when_the_gitignored_corpus_is_absent(
    monkeypatch, tmp_path
) -> None:
    """`data/curated/raw_tlc/` is ~37 GB and gitignored. Nothing to benchmark is not
    a failure, so CI stays green -- and no stale artifact is overwritten with an
    empty one."""
    monkeypatch.setattr(bench, "source_files", lambda pattern: [])
    out_dir = tmp_path / "empty"
    assert bench.main(["--rungs", "1000", "--out-dir", str(out_dir)]) == 0
    assert not (out_dir / "teardown_scale_results.json").exists()


def test_no_verdict_is_offered_when_nothing_was_measured() -> None:
    """An unmeasured bottleneck is not a measured one. With no successful rung
    the harness must refuse a verdict rather than guess one in either
    direction."""
    payload = {
        "results": [{"status": "child_died", "target_segments": 5_000_000}],
        "memory_slope": None,
    }
    verdict = bench._verdict(payload)
    assert "No rung completed" in verdict
    assert "stays unfired" in verdict


# --------------------------------------------------------------------------
# The committed artifact, when one exists, is the one this harness writes
# --------------------------------------------------------------------------


def test_the_committed_results_artifact_is_well_formed_and_self_describing() -> None:
    path = _BENCH_DIR / "teardown_scale_results.json"
    if not path.is_file():
        pytest.skip("no committed results artifact yet; run the harness to produce one")

    payload = json.loads(path.read_text(encoding="utf-8"))
    meta = payload["meta"]
    assert meta["measures"].startswith("aletheia/replay/teardown.py::teardown_deadhead")
    assert meta["machine"]["python_version"]
    assert meta["generated_at"]
    assert payload["results"]

    for record in payload["results"]:
        assert record["status"]
        if record["status"] != "ok":
            continue
        assert record["segments"] > 0
        assert record["timing"]["wall_s_median"] > 0
        assert record["peak_rss_bytes"] is None or record["peak_rss_bytes"] > 0
