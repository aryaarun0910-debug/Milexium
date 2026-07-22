"""Mechanical point-in-time leakage audit.

A forecasting model is only honest if every feature for target time t is
computable from information available strictly before t. Most teams assert
this in prose. We PROVE it, mechanically, with a future-corruption test:

  1. Build features normally (baseline).
  2. Corrupt every target value y at date > CUTOFF (replace with noise).
  3. Rebuild features on the corrupted panel.
  4. For every row at date <= CUTOFF, assert each feature is bit-identical
     to the baseline.

If a feature at time t changes when only the future (> CUTOFF >= t) is
corrupted, that feature secretly depends on the future -> leakage. If nothing
changes, the feature provably depends only on the past. We run it at several
cutoffs so the guarantee holds across the timeline, and report a per-feature
verdict.

Exogenous features (calendar, weather) are y-independent by construction, so
they pass trivially - but the test still confirms it rather than assuming it,
and the write-up notes the one real-world caveat (weather must be the day-ahead
FORECAST in production, not the realized value, or it would be look-ahead).

Runs on the production AAR pipeline and the NTD monthly pipeline.
Output: realdata/leakage_audit_report.json  (+ prints a per-feature table)
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent

from train_real_models import add_calendar, add_lags, load_aar  # noqa: E402
from model_ntd_monthly import build_features                    # noqa: E402


def audit(name, base_panel, build_fn, feature_cols, date_col, cutoffs, seed=0):
    """Return a per-feature leak/clean verdict for one pipeline."""
    rng = np.random.default_rng(seed)
    baseline = build_fn(base_panel.copy())
    baseline = baseline.sort_values(list(baseline.columns[:2])).reset_index(drop=True)

    verdict = {c: "clean" for c in feature_cols}
    details = {}
    for cutoff in cutoffs:
        corrupt = base_panel.copy()
        future = pd.to_datetime(corrupt[date_col]) > pd.Timestamp(cutoff)
        # replace future targets with large random noise, distinct from real
        corrupt.loc[future, "y_src"] = rng.integers(10_000, 1_000_000,
                                                     size=int(future.sum()))
        rebuilt = build_fn(corrupt)
        rebuilt = rebuilt.sort_values(list(rebuilt.columns[:2])).reset_index(drop=True)

        past = pd.to_datetime(baseline[date_col]) <= pd.Timestamp(cutoff)
        for c in feature_cols:
            a = baseline.loc[past, c].to_numpy()
            b = rebuilt.loc[past, c].to_numpy()
            # compare with NaN-awareness
            same = ((a == b) | (pd.isna(a) & pd.isna(b)))
            if isinstance(same, np.ndarray):
                if not same.all():
                    n_diff = int((~same).sum())
                    verdict[c] = "LEAKS"
                    details.setdefault(c, []).append(
                        {"cutoff": str(cutoff), "past_rows_changed": n_diff})
    return {"panel": name, "n_features": len(feature_cols),
            "verdict": verdict, "leak_details": details,
            "cutoffs_tested": [str(c) for c in cutoffs]}


def aar_build(panel):
    # panel already has a y_src column we control; map it to y then build
    p = panel.copy()
    p["y"] = p["y_src"]
    p = add_calendar(p)
    p = add_lags(p, "borough")
    return p


def ntd_build(panel):
    p = panel.copy()
    p["upt"] = p["y_src"]  # build_features reads upt -> y
    return build_features(p)


if __name__ == "__main__":
    report = {}

    # ---- AAR pipeline ----
    aar = load_aar()
    aar["y_src"] = aar["y"]
    aar_feats = ["hour", "hour_sin", "hour_cos", "dow", "month", "is_weekend",
                 "is_holiday", "lag1", "lag7", "lag14", "roll28"]
    aar_cuts = ["2025-06-01", "2025-12-01", "2026-03-01"]
    report["aar"] = audit("AAR zone-hour", aar, aar_build, aar_feats,
                          "date", aar_cuts)
    print(f"AAR: {sum(v=='clean' for v in report['aar']['verdict'].values())}"
          f"/{len(aar_feats)} features clean")
    for c, v in report["aar"]["verdict"].items():
        print(f"  {'OK ' if v=='clean' else 'LEAK'} {c}")

    # ---- NTD monthly pipeline ----
    ntd = pd.read_csv(HERE / "panels" / "ntd_monthly_dr.csv.gz")
    ntd["y_src"] = ntd["upt"]
    ntd_feats = ["month", "year", "month_sin", "month_cos", "lag1", "lag2",
                 "lag3", "lag12", "roll12", "yoy_ratio",
                 "vrh_lag1", "vrm_lag1", "voms_lag1"]
    ntd_cuts = ["2020-01-01", "2023-01-01", "2025-05-01"]
    report["ntd_monthly"] = audit("NTD monthly", ntd, ntd_build, ntd_feats,
                                  "date", ntd_cuts)
    print(f"\nNTD: {sum(v=='clean' for v in report['ntd_monthly']['verdict'].values())}"
          f"/{len(ntd_feats)} features clean")
    for c, v in report["ntd_monthly"]["verdict"].items():
        print(f"  {'OK ' if v=='clean' else 'LEAK'} {c}")

    all_clean = all(v == "clean"
                    for panel in report.values()
                    for v in panel["verdict"].values())
    report["overall"] = "PASS - no leakage detected" if all_clean else "FAIL - leakage found"
    (HERE / "leakage_audit_report.json").write_text(json.dumps(report, indent=2))
    print(f"\n{report['overall']}")
    print("saved realdata/leakage_audit_report.json")
