"""H5b -- which structural levers actually move demand-response cost per trip?

Run:  py -3 research/h5b_structure_vs_cost.py

Four questions, none of them in the brief, all answerable from data on disk.

  (a) DEADHEAD. Milexium's commercial premise is that deadhead is worth
      attacking. Does deadhead share actually explain cost per trip across
      agencies? (ECON, 2024 cross-section -- the only year with deadhead.)
  (b) TAXI/TNC. Does moving demand-response trips to taxi/TNC contractors
      (TOS = TX/TN) lower real cost per trip? Tested cross-sectionally AND
      within-agency, because the cross-section is confounded by which agencies
      choose to contract.
  (c) PURCHASED vs DIRECTLY OPERATED. Same question for TOS = PT vs DO.
  (d) SCALE. Is there a scale economy in demand response, and is it monotone?

The within-agency tests are the ones that carry weight: an agency compared to
itself has the same geography, the same clientele and the same wage market.
"""

from __future__ import annotations

import csv
import json
import math
import random
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
import sys  # noqa: E402

sys.path.insert(0, str(HERE))
from lib import ECON, mean, median, ols, pct, pearson, say, spearman  # noqa: E402


def bucket_report(pairs, label, nbuckets=5):
    """pairs = [(x, y)]; report y by quantile bucket of x.

    Ties in x are broken RANDOMLY (fixed seed), not by y. Sorting tuples would
    order tied x by y and manufacture a perfectly monotone relationship out of
    nothing -- which is exactly what happened on the first run of this script
    for the zero-inflated contracting shares. For variables with a large point
    mass (most agencies contract 0%), use group_report instead; quantiles of a
    mostly-constant variable are not meaningful however the ties are broken.
    """
    rnd = random.Random(0)
    pairs = sorted(pairs, key=lambda p: (p[0], rnd.random()))
    n = len(pairs)
    say(f"    {label} (n={n}, quintiles of x):")
    for i in range(nbuckets):
        lo, hi = i * n // nbuckets, (i + 1) * n // nbuckets
        chunk = pairs[lo:hi]
        if not chunk:
            continue
        xs = [c[0] for c in chunk]
        ys = [c[1] for c in chunk]
        say(
            f"      Q{i+1}  x in [{min(xs):8.4f},{max(xs):8.4f}]  "
            f"median y = {median(ys):10.2f}   mean y = {mean(ys):10.2f}   n={len(chunk)}"
        )


def main() -> None:
    out = {}
    rows = json.loads((HERE / "dr_panel.json").read_text(encoding="utf-8"))
    by = defaultdict(dict)
    for r in rows:
        by[r["ntd_id"]][r["year"]] = r

    # ---------------- (a) deadhead vs cost, 2024 -------------------------
    say("=" * 74)
    say("(a) Does deadhead share explain cost per trip?  ECON, 2024 cross-section")
    say("=" * 74)
    econ = [
        r
        for r in csv.DictReader(open(ECON, newline="", encoding="utf-8-sig"))
        if r["report_year"] == "2024"
    ]
    pts = []
    for r in econ:
        try:
            dh = float(r["deadhead_pct_hours"] or 0)
            cpt = float(r["cost_per_trip"] or 0)
            tpv = float(r["trips_per_vrh"] or 0)
            cpv = float(r["cost_per_vrh"] or 0)
            trips = float(r["trips"] or 0)
        except ValueError:
            continue
        if dh <= 0 or dh >= 0.95 or cpt <= 0 or tpv <= 0 or cpv <= 0:
            continue
        pts.append(
            {
                "agency": r["agency"],
                "dh": dh,
                "cpt": cpt,
                "tpv": tpv,
                "cpv": cpv,
                "trips": trips,
            }
        )
    say(f"  agencies with usable 2024 deadhead: {len(pts)}")
    dh = [p["dh"] for p in pts]
    lcpt = [math.log(p["cpt"]) for p in pts]
    say(f"  Pearson (deadhead share, log cost/trip)  = {pearson(dh, lcpt):+.3f}")
    say(f"  Spearman(deadhead share, cost/trip)      = {spearman(dh,[p['cpt'] for p in pts]):+.3f}")
    say(
        f"  Spearman(deadhead share, trips per VRH)  = "
        f"{spearman(dh,[p['tpv'] for p in pts]):+.3f}"
    )
    say(
        f"  Spearman(deadhead share, cost per VRH)   = "
        f"{spearman(dh,[p['cpv'] for p in pts]):+.3f}"
    )
    bucket_report([(p["dh"], p["cpt"]) for p in pts], "cost per trip by deadhead quintile")
    beta, r2 = ols([[p["dh"]] for p in pts], lcpt)
    say(f"  OLS log(cost/trip) ~ deadhead_share: slope {beta[1]:+.3f}, R2 = {r2:.4f}")
    say(
        "  interpretation: a 10pp rise in deadhead share is associated with a "
        f"{100*(math.exp(0.10*beta[1])-1):+.1f}% change in cost per trip."
    )
    out["deadhead"] = {
        "n": len(pts),
        "pearson_dh_logcpt": pearson(dh, lcpt),
        "spearman_dh_cpt": spearman(dh, [p["cpt"] for p in pts]),
        "spearman_dh_tpv": spearman(dh, [p["tpv"] for p in pts]),
        "spearman_dh_cpv": spearman(dh, [p["cpv"] for p in pts]),
        "ols_slope_log": beta[1],
        "ols_r2": r2,
    }

    # ---------------- (b)(c) service delivery mode -----------------------
    say("\n" + "=" * 74)
    say("(b)(c) Does contracting out lower cost per trip?")
    say("=" * 74)
    y24 = [r for r in rows if r["year"] == 2024 and r["upt"] > 5000]
    say(f"  2024 DR agencies with >5,000 trips: {len(y24)}")
    for key, name in (
        ("taxi_tnc_share_of_dr_upt", "taxi/TNC share of DR trips"),
        ("pt_share_of_dr_upt", "purchased-transportation share of DR trips"),
    ):
        vals = [r[key] for r in y24]
        nz = [v for v in vals if v > 0.01]
        say(f"\n  {name}: {len(nz)}/{len(vals)} agencies above 1%; median among those {median(nz):.3f}")
        pairs = [(r[key], r["cpt_2024usd"]) for r in y24]
        say(f"    Spearman(share, cost per trip) = {spearman([p[0] for p in pairs],[p[1] for p in pairs]):+.3f}")
        groups = [
            ("exactly 0%", lambda v: v <= 0.001),
            ("0-25%", lambda v: 0.001 < v <= 0.25),
            ("25-75%", lambda v: 0.25 < v <= 0.75),
            (">75%", lambda v: v > 0.75),
        ]
        say(f"    cost/trip by {name} GROUP (point mass at zero -> groups, not quantiles):")
        for gname, test in groups:
            ys = [p[1] for p in pairs if test(p[0])]
            if ys:
                say(
                    f"      {gname:<12} n={len(ys):>5}  median cost/trip = ${median(ys):8.2f}"
                    f"   mean = ${mean(ys):8.2f}"
                )

    # within-agency: 2015->2024 change in share vs change in real cost/trip
    say("\n  WITHIN-AGENCY (the test that controls for who chooses to contract):")
    for key, name in (
        ("taxi_tnc_share_of_dr_upt", "taxi/TNC share"),
        ("pt_share_of_dr_upt", "purchased-transportation share"),
    ):
        d_share, d_cost = [], []
        movers = []
        for nid, yrs in by.items():
            a, b = yrs.get(2015), yrs.get(2024)
            if not a or not b or a["upt"] < 5000 or b["upt"] < 5000:
                continue
            ds = b[key] - a[key]
            dc = math.log(b["cpt_2024usd"] / a["cpt_2024usd"])
            if abs(dc) > math.log(4):
                continue
            d_share.append(ds)
            d_cost.append(dc)
            if abs(ds) > 0.25:
                movers.append((ds, dc, a["agency"]))
        say(
            f"    {name}: n={len(d_share)}  "
            f"Pearson(Dshare, Dlog real cost/trip) = {pearson(d_share,d_cost):+.3f}  "
            f"Spearman = {spearman(d_share,d_cost):+.3f}"
        )
        up = [c for s, c in zip(d_share, d_cost) if s > 0.25]
        flat = [c for s, c in zip(d_share, d_cost) if abs(s) <= 0.05]
        down = [c for s, c in zip(d_share, d_cost) if s < -0.25]
        for lab, grp in (("increased >25pp", up), ("changed <5pp", flat), ("decreased >25pp", down)):
            if grp:
                say(
                    f"      agencies that {lab:<16} n={len(grp):>4}  "
                    f"median real cost/trip change = {100*(math.exp(median(grp))-1):+.1f}%"
                )
        out.setdefault("contracting", {})[key] = {
            "n": len(d_share),
            "pearson": pearson(d_share, d_cost),
            "spearman": spearman(d_share, d_cost),
            "median_change_increasers": median(up) if up else None,
            "n_increasers": len(up),
            "median_change_stable": median(flat) if flat else None,
            "n_stable": len(flat),
            "median_change_decreasers": median(down) if down else None,
            "n_decreasers": len(down),
        }

    # ---------------- (d) scale ------------------------------------------
    say("\n" + "=" * 74)
    say("(d) Are there scale economies in demand response?  2024")
    say("=" * 74)
    pairs = [(math.log(r["upt"]), r["cpt_2024usd"]) for r in y24]
    say(f"  Spearman(log trips, cost per trip) = {spearman([p[0] for p in pairs],[p[1] for p in pairs]):+.3f}")
    bucket_report(pairs, "cost per trip by trip-volume quintile", nbuckets=10)
    out["scale"] = {
        "n": len(pairs),
        "spearman_logupt_cpt": spearman([p[0] for p in pairs], [p[1] for p in pairs]),
    }

    (HERE / "h5b_structure_vs_cost.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    say("\nwrote research/h5b_structure_vs_cost.json")


if __name__ == "__main__":
    main()
