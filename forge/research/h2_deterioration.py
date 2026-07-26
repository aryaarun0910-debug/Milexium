"""H2 -- is next-year cost deterioration predictable from prior-year structure?

Run with the ML interpreter:  py -3 forge/research/h2_deterioration.py

Target
------
y = log( real cost-per-trip[t+1] / real cost-per-trip[t] ), demand response only,
both endpoints deflated to 2024 dollars. Positive y = deterioration.

Features are strictly time-t (and t-1 for momentum). No t+1 quantity ever
enters X. The split is by TARGET YEAR, so the test years are genuinely in the
future relative to every training row.

Baselines the model must beat to mean anything:
  zero      -- predict no change
  train_mean-- predict the training-set average change (a pure level shift)
  momentum  -- predict last year's change repeats
If a fitted model cannot beat `zero` out of sample, there is no signal.
"""

from __future__ import annotations

import json
import math
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import roc_auc_score

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# Trim bound on the target. NTD is self-reported and carries genuine data
# errors (agencies that restate trips by an order of magnitude). Anything
# beyond a 3x year-on-year move in real cost per trip is treated as a
# reporting artifact, not an operational event. The count trimmed is reported.
TRIM = math.log(3.0)

FEATURES = [
    "log_upt",
    "log_uza_pop",
    "trips_per_vrh",
    "cost_per_vrh_2024usd",
    "log_cpt",
    "prev_dlog_cpt",
    "prev_dlog_upt",
    "dr_share_of_agency_upt",
    "taxi_tnc_share_of_dr_upt",
    "pt_share_of_dr_upt",
    "farebox_recovery",
    "admin_share",
    "miles_per_hour",
    "trips_per_voms",
]


def build() -> pd.DataFrame:
    rows = json.loads((HERE / "dr_panel.json").read_text(encoding="utf-8"))
    df = pd.DataFrame(rows)
    df = df.sort_values(["ntd_id", "year"]).reset_index(drop=True)

    g = df.groupby("ntd_id")
    df["log_cpt"] = np.log(df["cpt_2024usd"])
    df["log_upt"] = np.log(df["upt"])
    df["log_uza_pop"] = np.log(df["uza_population"].clip(lower=1))
    df["trips_per_voms"] = df["upt"] / df["voms"].replace(0, np.nan)

    # strictly-past deltas
    df["prev_dlog_cpt"] = df["log_cpt"] - g["log_cpt"].shift(1)
    df["prev_dlog_upt"] = df["log_upt"] - g["log_upt"].shift(1)
    # target: next year
    df["y"] = g["log_cpt"].shift(-1) - df["log_cpt"]
    df["target_year"] = df["year"] + 1
    # only keep rows where t+1 is genuinely the consecutive year for that agency
    df["next_year_actual"] = g["year"].shift(-1)
    df = df[df["next_year_actual"] == df["target_year"]]
    return df


def metrics(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    ss_res = float(((y - p) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    return {
        "n": int(len(y)),
        "mae": float(np.abs(y - p).mean()),
        "rmse": float(np.sqrt(((y - p) ** 2).mean())),
        # R2 vs the TEST mean (standard), and vs zero (the honest "did you beat
        # doing nothing" question, since the test mean is not knowable ex ante)
        "r2_vs_test_mean": 1 - ss_res / ss_tot if ss_tot else None,
        "r2_vs_zero": 1 - ss_res / float((y**2).sum()) if (y**2).sum() else None,
    }


def main() -> None:
    df = build()
    n_all = len(df)
    trimmed = df[df["y"].abs() > TRIM]
    df = df[df["y"].abs() <= TRIM].copy()
    print(f"transitions available: {n_all}")
    print(f"trimmed |y| > log(3): {len(trimmed)} ({100*len(trimmed)/n_all:.2f}%)")

    d = df.dropna(subset=FEATURES + ["y"]).copy()
    print(f"complete-case rows: {len(d)}  agencies: {d['ntd_id'].nunique()}")
    print(
        "target years:",
        dict(sorted(d["target_year"].value_counts().items())),
    )

    results = {"config": {"trim_log": TRIM, "features": FEATURES}, "runs": {}}

    for label, drop_covid in (("all_years", False), ("ex_covid", True)):
        dd = d.copy()
        if drop_covid:
            # remove any transition whose source or target year is 2020 or 2021
            dd = dd[~dd["year"].isin([2019, 2020, 2021]) & ~dd["target_year"].isin([2020, 2021])]
        run = {}
        for test_year in (2023, 2024):
            tr = dd[dd["target_year"] < test_year]
            te = dd[dd["target_year"] == test_year]
            if len(tr) < 200 or len(te) < 100:
                continue
            Xtr, ytr = tr[FEATURES].values, tr["y"].values
            Xte, yte = te[FEATURES].values, te["y"].values

            preds = {
                "zero": np.zeros(len(yte)),
                "train_mean": np.full(len(yte), ytr.mean()),
                "momentum": te["prev_dlog_cpt"].values,
            }
            mu, sd = Xtr.mean(0), Xtr.std(0)
            sd[sd == 0] = 1
            ridge = Ridge(alpha=10.0).fit((Xtr - mu) / sd, ytr)
            preds["ridge"] = ridge.predict((Xte - mu) / sd)
            gbr = GradientBoostingRegressor(
                n_estimators=300, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=0
            ).fit(Xtr, ytr)
            preds["gbr"] = gbr.predict(Xte)

            yr = {"train_n": int(len(tr)), "models": {}}
            for name, p in preds.items():
                yr["models"][name] = metrics(yte, p)

            # Commercially the useful question is not R2, it is: can we flag
            # the agencies about to deteriorate worst? Top-quintile detection.
            thresh = np.quantile(yte, 0.8)
            lab = (yte >= thresh).astype(int)
            for name in ("ridge", "gbr", "momentum"):
                p = np.nan_to_num(preds[name])
                yr["models"][name]["auc_top_quintile"] = float(roc_auc_score(lab, p))
                k = max(1, int(0.2 * len(yte)))
                top = np.argsort(-p)[:k]
                yr["models"][name]["precision_at_top20pct"] = float(lab[top].mean())
                yr["models"][name]["mean_actual_y_in_flagged"] = float(yte[top].mean())
            yr["base_rate_top_quintile"] = 0.2
            yr["mean_actual_y_all"] = float(yte.mean())
            yr["median_actual_y_all"] = float(np.median(yte))
            yr["gbr_feature_importance"] = dict(
                sorted(
                    zip(FEATURES, [float(v) for v in gbr.feature_importances_]),
                    key=lambda kv: -kv[1],
                )
            )
            yr["ridge_coefs"] = dict(
                sorted(
                    zip(FEATURES, [float(v) for v in ridge.coef_]),
                    key=lambda kv: -abs(kv[1]),
                )
            )
            run[str(test_year)] = yr
        results["runs"][label] = run

    # ---- how much deterioration is there, and is it dispersed? -----------
    bal = d.copy()
    results["dispersion"] = {}
    for y in sorted(d["target_year"].unique()):
        s = d[d["target_year"] == y]["y"]
        results["dispersion"][int(y)] = {
            "n": int(len(s)),
            "mean_dlog": float(s.mean()),
            "median_dlog": float(s.median()),
            "p10": float(s.quantile(0.10)),
            "p90": float(s.quantile(0.90)),
            "sd": float(s.std()),
        }

    (HERE / "h2_deterioration.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    # ---- print ----------------------------------------------------------
    for label, run in results["runs"].items():
        print(f"\n=== {label} ===")
        for ty, yr in run.items():
            print(f"  target year {ty}  (train n={yr['train_n']}, test n={yr['models']['zero']['n']})")
            print(f"    actual mean dlog cpt = {yr['mean_actual_y_all']:+.4f}  median = {yr['median_actual_y_all']:+.4f}")
            print(f"      {'model':<12}{'MAE':>8}{'R2 vs 0':>10}{'R2 vs mean':>12}{'AUC':>8}{'prec@20':>9}")
            for name, m in yr["models"].items():
                auc = m.get("auc_top_quintile")
                pr = m.get("precision_at_top20pct")
                print(
                    f"      {name:<12}{m['mae']:>8.4f}{m['r2_vs_zero']:>10.4f}"
                    f"{m['r2_vs_test_mean']:>12.4f}"
                    f"{(f'{auc:.3f}' if auc else '-'):>8}"
                    f"{(f'{pr:.3f}' if pr is not None else '-'):>9}"
                )
            top = list(yr["gbr_feature_importance"].items())[:6]
            print("    top GBR features: " + ", ".join(f"{k}={v:.3f}" for k, v in top))

    print("\n=== dispersion of next-year real cost-per-trip change (DR) ===")
    print(f"  {'yr':<6}{'n':>6}{'mean':>9}{'median':>9}{'p10':>9}{'p90':>9}{'sd':>9}")
    for y, s in results["dispersion"].items():
        print(
            f"  {y:<6}{s['n']:>6}{s['mean_dlog']:>9.4f}{s['median_dlog']:>9.4f}"
            f"{s['p10']:>9.4f}{s['p90']:>9.4f}{s['sd']:>9.4f}"
        )
    print("\nwrote forge/research/h2_deterioration.json")


if __name__ == "__main__":
    main()
