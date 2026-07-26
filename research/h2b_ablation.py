"""H2b -- is the deterioration ranking signal REAL, or is it mean reversion?

Run:  py -3 research/h2b_ablation.py

H2 found a consistent AUC ~0.60 for flagging the worst-deteriorating quintile.
The top feature was `log_cpt` -- the CURRENT cost-per-trip level. That is exactly
what a mechanical artifact looks like: if year t's cost per trip is understated
by reporting noise, then t+1 mechanically "deteriorates", and a model that
learns "low level now => rise next year" scores well while knowing nothing
operational.

Three ablations separate the two explanations:

  A_full        every feature (the H2 model)
  B_structural  drop `log_cpt` and `prev_dlog_cpt` -- no level, no momentum.
                Only scale, productivity, unit cost, mix, geography.
  C_level_only  ONLY `log_cpt`. If C ~= A, the "model" is a level rule.

Plus a fourth check that kills the noise story if it survives it:
  D_lagged_level  replace log_cpt[t] with log_cpt[t-1]. Reporting noise in year
                t cannot be present in year t-1, so if the signal is pure noise
                mean-reversion, D collapses toward chance.

Target is additionally run in SECTOR-DEMEANED form (y minus that target year's
panel median), because a sector-wide shock is not something a model could have
known and not something a customer can act on.
"""

from __future__ import annotations

import json
import math
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import roc_auc_score

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
TRIM = math.log(3.0)

STRUCTURAL = [
    "log_upt",
    "log_uza_pop",
    "trips_per_vrh",
    "cost_per_vrh_2024usd",
    "prev_dlog_upt",
    "dr_share_of_agency_upt",
    "taxi_tnc_share_of_dr_upt",
    "pt_share_of_dr_upt",
    "farebox_recovery",
    "admin_share",
    "miles_per_hour",
    "trips_per_voms",
]
SETS = {
    "A_full": STRUCTURAL + ["log_cpt", "prev_dlog_cpt"],
    "B_structural": STRUCTURAL,
    "C_level_only": ["log_cpt"],
    "D_lagged_level": STRUCTURAL + ["lag_log_cpt"],
}


def build() -> pd.DataFrame:
    rows = json.loads((HERE / "dr_panel.json").read_text(encoding="utf-8"))
    df = pd.DataFrame(rows).sort_values(["ntd_id", "year"]).reset_index(drop=True)
    g = df.groupby("ntd_id")
    df["log_cpt"] = np.log(df["cpt_2024usd"])
    df["log_upt"] = np.log(df["upt"])
    df["log_uza_pop"] = np.log(df["uza_population"].clip(lower=1))
    df["trips_per_voms"] = df["upt"] / df["voms"].replace(0, np.nan)
    df["prev_dlog_cpt"] = df["log_cpt"] - g["log_cpt"].shift(1)
    df["prev_dlog_upt"] = df["log_upt"] - g["log_upt"].shift(1)
    df["lag_log_cpt"] = g["log_cpt"].shift(1)
    df["lag_year"] = g["year"].shift(1)
    df["y"] = g["log_cpt"].shift(-1) - df["log_cpt"]
    df["target_year"] = df["year"] + 1
    df = df[(g["year"].shift(-1) == df["target_year"]) & (df["lag_year"] == df["year"] - 1)]
    df = df[df["y"].abs() <= TRIM].copy()
    # sector-demeaned target
    df["y_demeaned"] = df["y"] - df.groupby("target_year")["y"].transform("median")
    return df


def run(d, feats, target, test_year):
    cols = list(feats)
    dd = d.dropna(subset=cols + [target])
    tr, te = dd[dd["target_year"] < test_year], dd[dd["target_year"] == test_year]
    if len(tr) < 200 or len(te) < 100:
        return None
    Xtr, ytr = tr[cols].values, tr[target].values
    Xte, yte = te[cols].values, te[target].values
    mu, sd = Xtr.mean(0), Xtr.std(0)
    sd[sd == 0] = 1
    out = {}
    models = {
        "ridge": Ridge(alpha=10.0).fit((Xtr - mu) / sd, ytr),
        "gbr": GradientBoostingRegressor(
            n_estimators=300, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=0
        ).fit(Xtr, ytr),
    }
    thresh = np.quantile(yte, 0.8)
    lab = (yte >= thresh).astype(int)
    for name, m in models.items():
        p = m.predict((Xte - mu) / sd) if name == "ridge" else m.predict(Xte)
        k = max(1, int(0.2 * len(yte)))
        top = np.argsort(-p)[:k]
        ss_res = float(((yte - p) ** 2).sum())
        out[name] = {
            "n_test": int(len(yte)),
            "n_train": int(len(tr)),
            "auc": float(roc_auc_score(lab, p)),
            "precision_at_20pct": float(lab[top].mean()),
            "lift": float(lab[top].mean() / 0.2),
            "mean_y_flagged": float(yte[top].mean()),
            "mean_y_all": float(yte.mean()),
            "r2_vs_zero": float(1 - ss_res / float((yte**2).sum())),
        }
    return out


def main() -> None:
    d = build()
    print(f"rows with full lag/lead structure: {len(d)}  agencies {d['ntd_id'].nunique()}")
    results = {}
    for target in ("y", "y_demeaned"):
        results[target] = {}
        for test_year in (2023, 2024):
            results[target][str(test_year)] = {}
            for label, feats in SETS.items():
                r = run(d, feats, target, test_year)
                if r:
                    results[target][str(test_year)][label] = r

    (HERE / "h2b_ablation.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    for target, byyear in results.items():
        print(f"\n=== target = {target} ===")
        for ty, sets in byyear.items():
            print(f"  test target-year {ty}")
            print(
                f"    {'featureset':<16}{'model':<8}{'AUC':>7}{'prec@20':>9}"
                f"{'lift':>7}{'meanY_flag':>12}{'meanY_all':>11}{'R2v0':>8}"
            )
            for label, models in sets.items():
                for name, m in models.items():
                    print(
                        f"    {label:<16}{name:<8}{m['auc']:>7.3f}{m['precision_at_20pct']:>9.3f}"
                        f"{m['lift']:>7.2f}{m['mean_y_flagged']:>12.4f}"
                        f"{m['mean_y_all']:>11.4f}{m['r2_vs_zero']:>8.4f}"
                    )
    print("\nwrote research/h2b_ablation.json")


if __name__ == "__main__":
    main()
