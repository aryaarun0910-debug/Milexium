"""H5d -- WHY did trips per vehicle revenue hour fall 10.6%?

Run:  python forge/research/h5d_productivity_anatomy.py

H5c established that 38% of the real cost-per-trip rise is falling productivity
(trips per vehicle revenue hour). Whether that is addressable by scheduling
software depends entirely on WHICH part of it moved, and the identity splits it
exactly two ways:

    trips/hour = (trips/mile) x (miles/hour)
    log(trips/hr) = -log(revenue miles per trip) + log(average speed)

  * revenue miles per trip up  -> trips got LONGER. That is land use and demand
    geography (sprawl, facility closures, longer medical trips). Scheduling can
    shorten the deadhead around a trip; it cannot shorten the trip.
  * average speed down -> congestion, or more time spent at kerbside per mile.
    Also largely exogenous.
  * If neither moved much and trips/hour still fell, the loss is in how vehicle
    time is packed -- ride-sharing rates, slack, wait -- which IS what
    scheduling determines.

Same balanced-panel discipline as H5c. Note the denominator is REVENUE hours and
REVENUE miles throughout, so deadhead is excluded from both sides of the
identity and cannot be the explanation here.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
import sys  # noqa: E402

sys.path.insert(0, str(HERE))
from lib import median, pct, say  # noqa: E402


def main() -> None:
    rows = json.loads((HERE / "dr_panel.json").read_text(encoding="utf-8"))
    by = defaultdict(dict)
    for r in rows:
        if r["vrm"] > 0:
            by[r["ntd_id"]][r["year"]] = r

    ids = [
        n
        for n, y in by.items()
        if 2015 in y and 2024 in y and y[2015]["upt"] > 5000 and y[2024]["upt"] > 5000
    ]
    say(f"balanced panel with revenue MILES reported in both years: n = {len(ids)}")

    def agg(year, num, den):
        return sum(by[n][year][num] for n in ids) / sum(by[n][year][den] for n in ids)

    out = {"n": len(ids)}
    say("\nAggregate identity, 2015 -> 2024:")
    say(f"  {'quantity':<28}{'2015':>12}{'2024':>12}{'change':>10}")
    for label, num, den in (
        ("trips per revenue hour", "upt", "vrh"),
        ("revenue miles per trip", "vrm", "upt"),
        ("average speed (mi/hr)", "vrm", "vrh"),
    ):
        v0, v1 = agg(2015, num, den), agg(2024, num, den)
        say(f"  {label:<28}{v0:>12.3f}{v1:>12.3f}{100*(v1/v0-1):>9.1f}%")
        out[label] = {"2015": v0, "2024": v1, "pct": v1 / v0 - 1}

    d_tpv = math.log(agg(2024, "upt", "vrh") / agg(2015, "upt", "vrh"))
    d_mpt = math.log(agg(2024, "vrm", "upt") / agg(2015, "vrm", "upt"))
    d_spd = math.log(agg(2024, "vrm", "vrh") / agg(2015, "vrm", "vrh"))
    say("\nEXACT split of the productivity change (log points):")
    say(f"  D log trips/hour        = {d_tpv:+.4f}  ({100*(math.exp(d_tpv)-1):+.1f}%)")
    say(f"    from trip LENGTH      = {-d_mpt:+.4f}  -> {100*(-d_mpt)/d_tpv:5.1f}% of the fall")
    say(f"    from SPEED            = {d_spd:+.4f}  -> {100*d_spd/d_tpv:5.1f}% of the fall")
    say(f"  (check: {-d_mpt + d_spd:+.4f} vs {d_tpv:+.4f})")
    out["decomposition"] = {
        "dlog_trips_per_hour": d_tpv,
        "dlog_miles_per_trip": d_mpt,
        "dlog_speed": d_spd,
        "share_from_trip_length": -d_mpt / d_tpv,
        "share_from_speed": d_spd / d_tpv,
    }

    say("\nPer-agency MEDIAN changes (concentration control):")
    per = {
        "trips per revenue hour": [
            by[n][2024]["upt"] / by[n][2024]["vrh"] / (by[n][2015]["upt"] / by[n][2015]["vrh"]) - 1
            for n in ids
        ],
        "revenue miles per trip": [
            by[n][2024]["vrm"] / by[n][2024]["upt"] / (by[n][2015]["vrm"] / by[n][2015]["upt"]) - 1
            for n in ids
        ],
        "average speed": [
            by[n][2024]["vrm"] / by[n][2024]["vrh"] / (by[n][2015]["vrm"] / by[n][2015]["vrh"]) - 1
            for n in ids
        ],
    }
    for k, vals in per.items():
        say(
            f"  {k:<26} median {100*median(vals):+7.1f}%   "
            f"p25 {100*pct(vals,25):+7.1f}%   p75 {100*pct(vals,75):+7.1f}%"
        )
        out.setdefault("per_agency_median", {})[k] = {
            "median": median(vals),
            "p25": pct(vals, 25),
            "p75": pct(vals, 75),
        }

    say("\nYear by year (all agencies reporting that year, >5k trips):")
    say(f"  {'year':<6}{'n':>6}{'trips/hr':>11}{'mi/trip':>11}{'speed':>9}")
    for y in range(2015, 2025):
        iy = [n for n in by if y in by[n] and by[n][y]["upt"] > 5000 and by[n][y]["vrm"] > 0]
        u = sum(by[n][y]["upt"] for n in iy)
        h = sum(by[n][y]["vrh"] for n in iy)
        m = sum(by[n][y]["vrm"] for n in iy)
        say(f"  {y:<6}{len(iy):>6}{u/h:>11.3f}{m/u:>11.3f}{m/h:>9.3f}")
        out.setdefault("by_year", {})[y] = {
            "n": len(iy),
            "trips_per_hour": u / h,
            "miles_per_trip": m / u,
            "speed": m / h,
        }

    (HERE / "h5d_productivity_anatomy.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    say("\nwrote forge/research/h5d_productivity_anatomy.json")


if __name__ == "__main__":
    main()
