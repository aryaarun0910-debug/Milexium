"""H5c -- is the demand-response cost rise a WAGE story or a PRODUCTIVITY story?

Run:  python research/h5c_cost_decomposition.py

Not in the brief, and arguably the most consequential question in it. The
identity is exact:

    cost per trip  =  cost per vehicle revenue hour  /  trips per vehicle revenue hour
    log(cpt)       =  log(cpv)                       -  log(tpv)

so the variance and the change decompose without any modelling assumption:

    var(log cpt) = var(log cpv) + var(log tpv) - 2 cov(log cpv, log tpv)
    D log cpt    = D log cpv    - D log tpv

If the rise is cost-per-hour, it is input prices -- wages, fuel, insurance,
contractor rates -- and scheduling software cannot touch it. If it is
trips-per-hour, it is productivity: how many rides an hour of vehicle time
yields, which IS what routing and scheduling determine. The commercial
consequence of the two answers is opposite, so it is worth being exact.

Balanced panel throughout: the same agencies at both endpoints, so composition
cannot manufacture the result. Aggregate and per-agency median both reported,
so concentration cannot either.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
import sys  # noqa: E402

sys.path.insert(0, str(HERE))
from lib import mean, median, pct, pearson, say  # noqa: E402


def var(xs):
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)


def cov(xs, ys):
    mx, my = mean(xs), mean(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (len(xs) - 1)


def main() -> None:
    rows = json.loads((HERE / "dr_panel.json").read_text(encoding="utf-8"))
    by = defaultdict(dict)
    for r in rows:
        by[r["ntd_id"]][r["year"]] = r

    out = {}

    # ---- 1. cross-sectional variance decomposition, 2024 -----------------
    say("=" * 76)
    say("1. WHY DO AGENCIES DIFFER?  cross-sectional variance of log cost/trip, 2024")
    say("=" * 76)
    y24 = [r for r in rows if r["year"] == 2024 and r["upt"] > 5000 and r["vrh"] > 0]
    lcpv = [math.log(r["cost_per_vrh_2024usd"]) for r in y24]
    ltpv = [math.log(r["trips_per_vrh"]) for r in y24]
    lcpt = [a - b for a, b in zip(lcpv, ltpv)]
    v = var(lcpt)
    say(f"  n = {len(y24)} agencies")
    say(f"  var(log cost/trip)      = {v:.4f}   sd = {math.sqrt(v):.4f}")
    say(f"  var(log cost/hour)      = {var(lcpv):.4f}  -> {100*var(lcpv)/v:5.1f}% of total")
    say(f"  var(log trips/hour)     = {var(ltpv):.4f}  -> {100*var(ltpv)/v:5.1f}% of total")
    say(f"  -2*cov(...)             = {-2*cov(lcpv,ltpv):.4f}  -> {100*(-2*cov(lcpv,ltpv))/v:5.1f}%")
    say(f"  corr(log cost/hr, log trips/hr) = {pearson(lcpv, ltpv):+.3f}")
    say(
        "\n  Read: productivity (trips per hour) accounts for "
        f"{100*var(ltpv)/v:.0f}% of the raw variance, input cost per hour for "
        f"{100*var(lcpv)/v:.0f}%."
    )
    out["cross_section_2024"] = {
        "n": len(y24),
        "var_log_cpt": v,
        "var_log_cpv": var(lcpv),
        "var_log_tpv": var(ltpv),
        "minus2cov": -2 * cov(lcpv, ltpv),
        "share_cpv": var(lcpv) / v,
        "share_tpv": var(ltpv) / v,
        "corr_cpv_tpv": pearson(lcpv, ltpv),
    }

    # ---- 2. the 2015->2024 change ----------------------------------------
    say("\n" + "=" * 76)
    say("2. WHY DID IT RISE?  balanced-panel change 2015 -> 2024 (2024 dollars)")
    say("=" * 76)
    ids = [n for n, yrs in by.items() if 2015 in yrs and 2024 in yrs]
    ids = [n for n in ids if by[n][2015]["upt"] > 5000 and by[n][2024]["upt"] > 5000]
    a = {n: by[n][2015] for n in ids}
    b = {n: by[n][2024] for n in ids}
    say(f"  balanced panel n = {len(ids)} agencies present in BOTH 2015 and 2024")

    def agg(d, num, den):
        return sum(d[n][num] for n in ids) / sum(d[n][den] for n in ids)

    for label, num, den, deflate in (
        ("cost per trip  (nominal)", "opex_nominal", "upt", False),
        ("cost per trip  (2024 $)", "opex_2024usd", "upt", True),
        ("cost per hour  (nominal)", "opex_nominal", "vrh", False),
        ("cost per hour  (2024 $)", "opex_2024usd", "vrh", True),
        ("trips per hour", "upt", "vrh", False),
    ):
        v0, v1 = agg(a, num, den), agg(b, num, den)
        say(f"  {label:<26} 2015 {v0:>10.3f}   2024 {v1:>10.3f}   {100*(v1/v0-1):+8.1f}%")
        out.setdefault("aggregate_change", {})[label.strip()] = {
            "2015": v0,
            "2024": v1,
            "pct_change": v1 / v0 - 1,
        }

    d_cpt = math.log(agg(b, "opex_2024usd", "upt") / agg(a, "opex_2024usd", "upt"))
    d_cpv = math.log(agg(b, "opex_2024usd", "vrh") / agg(a, "opex_2024usd", "vrh"))
    d_tpv = math.log(agg(b, "upt", "vrh") / agg(a, "upt", "vrh"))
    say("\n  EXACT decomposition of the REAL cost-per-trip rise (log points):")
    say(f"    D log real cost/trip  = {d_cpt:+.4f}   ({100*(math.exp(d_cpt)-1):+.1f}%)")
    say(f"      from real cost/hour = {d_cpv:+.4f}   -> {100*d_cpv/d_cpt:5.1f}% of the rise")
    say(f"      from trips/hour     = {-d_tpv:+.4f}   -> {100*(-d_tpv)/d_cpt:5.1f}% of the rise")
    say(f"    (check: {d_cpv - d_tpv:+.4f} vs {d_cpt:+.4f})")
    out["decomposition_real"] = {
        "dlog_cpt": d_cpt,
        "dlog_cpv": d_cpv,
        "dlog_tpv": d_tpv,
        "share_from_cost_per_hour": d_cpv / d_cpt,
        "share_from_productivity": -d_tpv / d_cpt,
    }

    # per-agency medians, so concentration cannot drive it
    say("\n  Per-agency MEDIAN changes (concentration control):")
    per = {
        "real cost/trip": [b[n]["cpt_2024usd"] / a[n]["cpt_2024usd"] - 1 for n in ids],
        "real cost/hour": [
            b[n]["cost_per_vrh_2024usd"] / a[n]["cost_per_vrh_2024usd"] - 1 for n in ids
        ],
        "trips/hour": [b[n]["trips_per_vrh"] / a[n]["trips_per_vrh"] - 1 for n in ids],
    }
    for k, vals in per.items():
        say(
            f"    {k:<16} median {100*median(vals):+7.1f}%   "
            f"p25 {100*pct(vals,25):+7.1f}%   p75 {100*pct(vals,75):+7.1f}%"
        )
        out.setdefault("per_agency_median_change", {})[k] = {
            "median": median(vals),
            "p25": pct(vals, 25),
            "p75": pct(vals, 75),
        }
    frac_prod_down = sum(1 for v in per["trips/hour"] if v < 0) / len(ids)
    frac_cost_up = sum(1 for v in per["real cost/hour"] if v > 0) / len(ids)
    say(f"\n    agencies whose PRODUCTIVITY fell 2015->2024:      {100*frac_prod_down:.1f}%")
    say(f"    agencies whose REAL COST PER HOUR rose 2015->2024: {100*frac_cost_up:.1f}%")
    out["fraction_productivity_fell"] = frac_prod_down
    out["fraction_real_cost_per_hour_rose"] = frac_cost_up

    # ---- 3. is it just COVID that never came back? -----------------------
    say("\n" + "=" * 76)
    say("3. Is the productivity loss a COVID scar, or did it start earlier?")
    say("=" * 76)
    say(f"  {'year':<6}{'n':>6}{'agg trips/hr':>15}{'median trips/hr':>18}{'agg real $/hr':>16}")
    for y in range(2015, 2025):
        ids_y = [n for n in by if y in by[n] and by[n][y]["upt"] > 5000]
        tot_u = sum(by[n][y]["upt"] for n in ids_y)
        tot_h = sum(by[n][y]["vrh"] for n in ids_y)
        tot_c = sum(by[n][y]["opex_2024usd"] for n in ids_y)
        med = median([by[n][y]["trips_per_vrh"] for n in ids_y])
        say(f"  {y:<6}{len(ids_y):>6}{tot_u/tot_h:>15.3f}{med:>18.3f}{tot_c/tot_h:>16.2f}")
        out.setdefault("by_year", {})[y] = {
            "n": len(ids_y),
            "agg_trips_per_hour": tot_u / tot_h,
            "median_trips_per_hour": med,
            "agg_real_cost_per_hour": tot_c / tot_h,
        }

    # pre-COVID only, balanced 2015->2019
    ids2 = [
        n
        for n in by
        if 2015 in by[n] and 2019 in by[n] and by[n][2015]["upt"] > 5000 and by[n][2019]["upt"] > 5000
    ]
    a2 = {n: by[n][2015] for n in ids2}
    b2 = {n: by[n][2019] for n in ids2}
    ag = lambda d, num, den: sum(d[n][num] for n in ids2) / sum(d[n][den] for n in ids2)  # noqa: E731
    d_cpt2 = math.log(ag(b2, "opex_2024usd", "upt") / ag(a2, "opex_2024usd", "upt"))
    d_cpv2 = math.log(ag(b2, "opex_2024usd", "vrh") / ag(a2, "opex_2024usd", "vrh"))
    d_tpv2 = math.log(ag(b2, "upt", "vrh") / ag(a2, "upt", "vrh"))
    say(f"\n  PRE-COVID balanced panel 2015->2019, n = {len(ids2)}:")
    say(f"    D log real cost/trip = {d_cpt2:+.4f} ({100*(math.exp(d_cpt2)-1):+.1f}%)")
    say(f"      from real cost/hour = {d_cpv2:+.4f} -> {100*d_cpv2/d_cpt2:5.1f}%")
    say(f"      from productivity   = {-d_tpv2:+.4f} -> {100*(-d_tpv2)/d_cpt2:5.1f}%")
    out["precovid_2015_2019"] = {
        "n": len(ids2),
        "dlog_cpt": d_cpt2,
        "dlog_cpv": d_cpv2,
        "dlog_tpv": d_tpv2,
        "share_from_cost_per_hour": d_cpv2 / d_cpt2,
        "share_from_productivity": -d_tpv2 / d_cpt2,
    }

    (HERE / "h5c_cost_decomposition.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    say("\nwrote research/h5c_cost_decomposition.json")


if __name__ == "__main__":
    main()
