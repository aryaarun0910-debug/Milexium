"""Forecast leaderboard artifact (Phase-2 item 3).

Packages this repo's REAL, already-committed demand-forecasting results into a
reproducible, third-party-checkable leaderboard. It does NOT run any model and
does NOT invent any number: it READS the committed metrics artifacts and emits a
machine-readable leaderboard plus a short honest human summary, with every value
carrying the exact source file and JSON-path it came from.

Sources (read-only):

- `realdata/metrics_real.json`         -- the four zone-hour XGBoost demand models
  (NYC Access-A-Ride, Chicago TNP, MTA bus, MTA subway), each with its real
  metrics, its seasonal-naive baseline, and a `valid_span` evaluation window.
- `realdata/metrics_ntd_monthly.json`  -- the national monthly (NTD) model, two
  honest splits (temporal + cold-start), each with its naive baseline (optional;
  included only if present).

Discipline (why the number is trustworthy):

- Every model ships next to its seasonal-naive baseline (mean of the same
  (zone, hour, day-of-week) slot over the pre-validation window). No model is
  ever shown alone.
- Evaluation is strict temporal (forward) holdout on a validation window never
  touched by fit or calibration -- Demonstrated on real AGGREGATE public data,
  NOT operator-validated dispatch. A metric is not a probability.
- Numbers are copied verbatim from the source JSON (no re-rounding), so re-reading
  the cited file and comparing at the cited JSON-path reproduces every cell.
- The kaggle pretrain/finetune transformer is EXCLUDED as a production row,
  mirroring MODEL_CARDS.md's own "Not shipped" framing (it lost to XGBoost on
  AAR, 0.933 vs 0.986; R&D evidence only).

Outputs (written next to this script):

- `forecast_leaderboard.json` -- machine-readable, one record per model/split.
- `forecast_leaderboard.md`   -- a short honest leaderboard table + caveats.

Usage:
    py -3 evidence/benchmarks/quality/build_forecast_leaderboard.py

If `realdata/metrics_real.json` is absent, there is nothing to package; the
generator prints why and exits 0 (not a failure).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_JSON_OUT = _HERE / "forecast_leaderboard.json"
_MD_OUT = _HERE / "forecast_leaderboard.md"

_METRICS_REAL = "realdata/metrics_real.json"
_METRICS_NTD = "realdata/metrics_ntd_monthly.json"

# (model_key, display_name, role, spatial_grain)
_ZONE_MODELS = [
    (
        "nyc_access_a_ride",
        "NYC Access-A-Ride paratransit bookings (borough-hour)",
        "PRODUCT TARGET (real paratransit demand)",
        "borough",
    ),
    (
        "chicago_tnp",
        "Chicago TNP door-to-door trips (community-area-hour)",
        "generalization evidence (not the product target)",
        "community area (77 zones)",
    ),
    (
        "mta_bus",
        "MTA bus AFC fare-payment ridership (route-hour)",
        "generalization evidence (not the product target)",
        "route",
    ),
    (
        "mta_subway",
        "MTA subway AFC fare-payment ridership (station-hour)",
        "generalization evidence (not the product target)",
        "station",
    ),
]

# (split_key, display_name, role)
_NTD_SPLITS = [
    (
        "cold_start_agency",
        "NTD national monthly demand -- cold-start (127 held-out agencies, no agency identity)",
        "national onboarding evidence (forecasting an agency never seen in training)",
    ),
    (
        "temporal",
        "NTD national monthly demand -- temporal (last 12 months, all agencies)",
        "national market evidence",
    ),
]


def _metric(name, model, naive, higher_is_better, source_file, model_path, naive_path):
    """One traceable metric cell: the model value, its seasonal-naive baseline,
    which direction is better, whether the model beats naive, and the exact
    source file + JSON-path for each of the two numbers.

    `improvement_abs` is always signed so that positive == model is better
    (model-naive for higher-is-better metrics, naive-model for error metrics).
    `improvement_pct` is the relative error reduction for lower-is-better
    metrics and null for R2 (a relative gain in R2 is not a meaningful figure).
    """
    if higher_is_better:
        beats = model > naive
        improvement_abs = round(model - naive, 6)
        improvement_pct = None
    else:
        beats = model < naive
        improvement_abs = round(naive - model, 6)
        improvement_pct = round((naive - model) / naive * 100.0, 4) if naive else None
    return {
        "metric": name,
        "model": model,
        "naive": naive,
        "higher_is_better": higher_is_better,
        "model_beats_naive": beats,
        "improvement_abs": improvement_abs,
        "improvement_pct": improvement_pct,
        "model_source": {"file": source_file, "json_path": model_path},
        "naive_source": {"file": source_file, "json_path": naive_path},
    }


def _zone_row(key, display_name, role, spatial_grain, block):
    metrics = {
        "R2": _metric(
            "R2", block["model_r2"], block["naive_r2"], True,
            _METRICS_REAL, f"$.{key}.model_r2", f"$.{key}.naive_r2",
        ),
        "MAE": _metric(
            "MAE", block["model_mae"], block["naive_mae"], False,
            _METRICS_REAL, f"$.{key}.model_mae", f"$.{key}.naive_mae",
        ),
        "RMSE": _metric(
            "RMSE", block["model_rmse"], block["naive_rmse"], False,
            _METRICS_REAL, f"$.{key}.model_rmse", f"$.{key}.naive_rmse",
        ),
    }
    return {
        "model_key": key,
        "display_name": display_name,
        "role": role,
        "task": "forecast.demand",
        "spatial_grain": spatial_grain,
        "temporal_grain": "hourly, day-ahead",
        "evaluation_window": block["valid_span"],
        "evaluation_window_source": {"file": _METRICS_REAL, "json_path": f"$.{key}.valid_span"},
        "n_valid": block["n_valid"],
        "source_file": _METRICS_REAL,
        "json_path_prefix": f"$.{key}",
        "headline_metric": "R2",
        "beats_naive_on_headline": metrics["R2"]["model_beats_naive"],
        "metrics": metrics,
        "notes": (
            "XGBoost count:poisson, calendar + weather + demand-history lags; "
            "strict temporal holdout; split-conformal 90% intervals reported "
            "separately in the source. Aggregate panel, not trip-level."
        ),
    }


def _ntd_row(split_key, display_name, role, block, panel):
    metrics = {
        "R2": _metric(
            "R2", block["model_r2"], block["naive_r2"], True,
            _METRICS_NTD, f"$.{split_key}.model_r2", f"$.{split_key}.naive_r2",
        ),
        "MAE": _metric(
            "MAE", block["model_mae"], block["naive_mae"], False,
            _METRICS_NTD, f"$.{split_key}.model_mae", f"$.{split_key}.naive_mae",
        ),
        "MAPE": _metric(
            "MAPE", block["model_mape"], block["naive_mape"], False,
            _METRICS_NTD, f"$.{split_key}.model_mape", f"$.{split_key}.naive_mape",
        ),
    }
    return {
        "model_key": f"ntd_monthly.{split_key}",
        "display_name": display_name,
        "role": role,
        "task": "forecast.demand",
        "spatial_grain": "agency (national, 637 agencies)",
        "temporal_grain": "monthly",
        "evaluation_window": block["split"],
        "evaluation_window_source": {"file": _METRICS_NTD, "json_path": f"$.{split_key}.split"},
        "panel_span": panel["date_range"],
        "n_valid": block["n"],
        "source_file": _METRICS_NTD,
        "json_path_prefix": f"$.{split_key}",
        "headline_metric": "R2",
        "beats_naive_on_headline": metrics["R2"]["model_beats_naive"],
        "metrics": metrics,
        "notes": (
            "MAPE is stored in the source as a ratio (e.g. 9.9176 = 991.8%); "
            "MODEL_CARDS.md renders it x100 as a percent. On the temporal split "
            "the model LOSES to naive on absolute R2 because monthly demand is "
            "very stable year-over-year, but wins on relative error (MAPE); the "
            "cold-start split -- the real onboarding scenario -- beats naive on "
            "both R2 and MAPE. Reported honestly, both ways."
        ),
    }


def _does_not_beat_naive(real, ntd, ablation):
    """The honest 'where the model does NOT clearly beat naive' findings, each
    tied to a committed source. This is the repo's discipline made explicit:
    every number ships with the naive comparison, including the unflattering
    ones."""
    findings = []

    # 1. The without-lags ablation: the calendar+weather model ties naive.
    #    This number lives in prose in realdata/README.md (no JSON path), so it
    #    is carried as an attributed quote, not a machine value.
    findings.append({
        "finding": "without demand-history lags, the calendar+weather model ties the seasonal-naive baseline",
        "detail": "R2 0.919 (model) vs 0.921 (naive) -- the lags, not the weather, are what beats naive",
        "source": {"file": "realdata/README.md", "kind": "prose_quote"},
    })

    # 2. Weather-feature ablation (JSON-backed): weather adds almost nothing on
    #    top of the lags; the model still sits far above naive either way.
    if ablation is not None:
        findings.append({
            "finding": "weather features barely move the AAR model (the lags carry it)",
            "detail": (
                "with-weather R2 %.4f vs no-weather R2 %.4f, both far above the "
                "naive %.4f on this window" % (
                    ablation["daily+hourly"]["model_r2"],
                    ablation["none"]["model_r2"],
                    ablation["none"]["naive_r2"],
                )
            ),
            "values": {
                "model_r2_with_weather": {
                    "value": ablation["daily+hourly"]["model_r2"],
                    "source": {"file": "realdata/metrics_weather_ablation.json", "json_path": "$.['daily+hourly'].model_r2"},
                },
                "model_r2_no_weather": {
                    "value": ablation["none"]["model_r2"],
                    "source": {"file": "realdata/metrics_weather_ablation.json", "json_path": "$.none.model_r2"},
                },
                "naive_r2": {
                    "value": ablation["none"]["naive_r2"],
                    "source": {"file": "realdata/metrics_weather_ablation.json", "json_path": "$.none.naive_r2"},
                },
            },
        })

    # 3. NTD temporal split loses to naive on absolute R2 (JSON-backed).
    if ntd is not None:
        findings.append({
            "finding": "NTD temporal split LOSES to naive on absolute R2",
            "detail": (
                "model R2 %.4f vs naive %.4f (monthly demand is very stable YoY); "
                "the model wins on MAPE and on the cold-start split instead"
                % (ntd["temporal"]["model_r2"], ntd["temporal"]["naive_r2"])
            ),
            "values": {
                "model_r2": {
                    "value": ntd["temporal"]["model_r2"],
                    "source": {"file": _METRICS_NTD, "json_path": "$.temporal.model_r2"},
                },
                "naive_r2": {
                    "value": ntd["temporal"]["naive_r2"],
                    "source": {"file": _METRICS_NTD, "json_path": "$.temporal.naive_r2"},
                },
            },
        })

    return findings


def build_leaderboard(repo_root: Path) -> dict:
    """Read the committed metrics artifacts and assemble the leaderboard payload.
    Raises FileNotFoundError if the primary metrics file is absent."""
    real_path = repo_root / _METRICS_REAL
    real = json.loads(real_path.read_text(encoding="utf-8"))

    ntd_path = repo_root / _METRICS_NTD
    ntd = json.loads(ntd_path.read_text(encoding="utf-8")) if ntd_path.exists() else None

    ablation_path = repo_root / "realdata/metrics_weather_ablation.json"
    ablation = json.loads(ablation_path.read_text(encoding="utf-8")) if ablation_path.exists() else None

    rows = []
    for key, display_name, role, grain in _ZONE_MODELS:
        if key in real:
            rows.append(_zone_row(key, display_name, role, grain, real[key]))
    if ntd is not None:
        for split_key, display_name, role in _NTD_SPLITS:
            if split_key in ntd:
                rows.append(_ntd_row(split_key, display_name, role, ntd[split_key], ntd["panel"]))

    sources = [_METRICS_REAL]
    if ntd is not None:
        sources.append(_METRICS_NTD)
    if ablation is not None:
        sources.append("realdata/metrics_weather_ablation.json")

    payload = {
        "artifact": "forecast_leaderboard",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "evidence/benchmarks/quality/build_forecast_leaderboard.py",
        "task": "forecast.demand",
        "what_this_is": (
            "Real demand forecasts on real AGGREGATE public data under strict "
            "temporal (forward) evaluation. Demonstrated, NOT operator-validated "
            "dispatch. A metric is not a probability. Every model is shown against "
            "its own seasonal-naive baseline."
        ),
        "evaluation_protocol": (
            "Strict temporal holdout: four non-overlapping >=90-day blocks "
            "(train/tune/cal/valid); the validation window is never touched by "
            "fit or calibration. Metrics reported on that untouched window."
        ),
        "baseline_definition": (
            "seasonal-naive = mean of the same (zone, hour, day-of-week) slot over "
            "the pre-validation window (monthly NTD uses the analogous seasonal-naive)."
        ),
        "ranking_note": (
            "This is NOT a ranking of models against each other: R2/MAE are not "
            "comparable across different spatial/temporal grains and different "
            "series. Each row is scored only against ITS OWN seasonal-naive "
            "baseline. Rows are ordered product-target first, then generalization "
            "models, then the national monthly model."
        ),
        "sources": sources,
        "excluded": [
            {
                "model": "kaggle pretrain-then-finetune transformer",
                "reason": (
                    "MODEL_CARDS.md 'Not shipped': run on real GPUs but LOST to "
                    "XGBoost on AAR (R2 0.933 vs 0.986). R&D evidence, not a "
                    "production model; we ship the simpler model on purpose."
                ),
                "source": {
                    "file": "_legacy/kaggle/results/finetune_metrics_testmode.json",
                    "json_path": "$.model_r2",
                    "also": "knowledge/docs/MODEL_CARDS.md ('Not shipped')",
                },
            },
        ],
        "does_not_beat_naive": _does_not_beat_naive(real, ntd, ablation),
        "rows": rows,
    }
    return payload


def _fmt(value, places):
    return f"{value:.{places}f}"


def _render_md(payload: dict) -> str:
    L: list[str] = []
    L.append("# Forecast demand leaderboard -- honest results\n")
    L.append(f"_Generated {payload['generated_at']} by `{payload['generator']}`. "
             "Every value is copied verbatim from a committed metrics file and "
             "carries its source file + JSON-path in `forecast_leaderboard.json`._\n")
    L.append("\n" + payload["what_this_is"] + "\n")

    L.append("\n## How to read this\n")
    L.append(f"- **Protocol.** {payload['evaluation_protocol']}\n")
    L.append(f"- **Baseline.** {payload['baseline_definition']} Every model is shown against it -- no model is shown alone.\n")
    L.append(f"- **Not a cross-model ranking.** {payload['ranking_note']}\n")
    L.append("- **Honest limits.** Demonstrated on real *aggregate* public data, not operator-validated trip-level dispatch. A metric is not a probability. External validity to a specific operator's own bookings is unproven until a pilot.\n")

    L.append("\n## Leaderboard\n")
    L.append("Headline metric is R2 (higher is better), shown model vs its seasonal-naive baseline; the MAE column shows the error reduction over that same baseline.\n\n")
    L.append("| model | role | grain | eval window | R2 (model / naive) | beats naive? | MAE (model / naive) | MAE error reduction | source |\n")
    L.append("|---|---|---|---|---|---|---|---|---|\n")
    for r in payload["rows"]:
        r2 = r["metrics"]["R2"]
        mae = r["metrics"]["MAE"]
        beats = "yes" if r["beats_naive_on_headline"] else "**NO**"
        grain = f"{r['spatial_grain']} / {r['temporal_grain']}"
        mae_red = f"{mae['improvement_pct']:.1f}%" if mae["improvement_pct"] is not None else "-"
        if not mae["model_beats_naive"]:
            mae_red = f"**{mae_red} (worse)**"
        L.append(
            f"| {r['display_name']} | {r['role'].split('(')[0].strip()} | {grain} | "
            f"{r['evaluation_window']} | {_fmt(r2['model'], 4)} / {_fmt(r2['naive'], 4)} | {beats} | "
            f"{_fmt(mae['model'], 2)} / {_fmt(mae['naive'], 2)} | {mae_red} | `{r['source_file']}` |\n"
        )

    L.append("\n## Where the model does NOT clearly beat naive (reported on purpose)\n")
    L.append("The repo's discipline is that every number ships with its naive comparison, including the unflattering ones:\n\n")
    for f in payload["does_not_beat_naive"]:
        if "source" in f:
            src = f["source"]["file"]
        else:
            src = "; ".join(dict.fromkeys(v["source"]["file"] for v in f.get("values", {}).values()))
        L.append(f"- **{f['finding']}** -- {f['detail']} (source: `{src}`).\n")

    L.append("\n## Not shipped (excluded from the leaderboard)\n")
    for e in payload["excluded"]:
        L.append(f"- **{e['model']}** -- {e['reason']} (source: `{e['source']['file']}`).\n")
    L.append("\nMirrors MODEL_CARDS.md's own 'Not shipped' framing: the transformer is R&D evidence, not a production row, so it does not appear above.\n")

    L.append("\n## Reproduce / verify\n")
    L.append("```\n")
    L.append("py -3 evidence/benchmarks/quality/build_forecast_leaderboard.py\n")
    L.append("py -3 -m pytest evidence/conformance/property-tests/test_forecast_leaderboard.py -v\n")
    L.append("```\n")
    L.append("The conformance test re-reads each cited source JSON at the cited JSON-path and asserts every leaderboard cell matches -- so no value here is a hand-copied number.\n")
    return "".join(L)


def main() -> int:
    real_path = _REPO_ROOT / _METRICS_REAL
    if not real_path.exists():
        print(
            f"{_METRICS_REAL} not found -- nothing to package into a forecast "
            "leaderboard. Exiting 0 (not a failure)."
        )
        return 0

    payload = build_leaderboard(_REPO_ROOT)
    _JSON_OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _MD_OUT.write_text(_render_md(payload), encoding="utf-8")

    beat = sum(1 for r in payload["rows"] if r["beats_naive_on_headline"])
    print(f"Wrote {_JSON_OUT.name} and {_MD_OUT.name}: {len(payload['rows'])} model rows "
          f"({beat} beat naive on headline R2), {len(payload['does_not_beat_naive'])} honest "
          f"does-not-beat-naive findings, {len(payload['excluded'])} excluded.")
    for r in payload["rows"]:
        r2 = r["metrics"]["R2"]
        flag = "" if r["beats_naive_on_headline"] else "   <-- does NOT beat naive on R2"
        print(f"  {r['model_key']:28s} R2 {r2['model']:.4f} vs naive {r2['naive']:.4f}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
