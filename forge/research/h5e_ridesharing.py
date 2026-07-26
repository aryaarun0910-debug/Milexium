"""H5e -- the productivity loss is LOST RIDE-SHARING, not longer trips.

Run:  python forge/research/h5e_ridesharing.py

H5d used vehicle revenue miles per trip as the productivity driver and concluded
"trips got longer". That measure is ambiguous and the conclusion was wrong: two
riders sharing one 10-mile vehicle run produce 5 vehicle-miles per trip; the
same two riders carried separately produce 10. Vehicle miles per trip therefore
rises when trips lengthen OR when ride-sharing falls, and those have opposite
commercial meanings.

Passenger Miles Traveled separates them exactly:

    vehicle revenue miles / trip = (passenger miles / trip) / (passenger miles /
                                                              vehicle mile)
    log(VRM/UPT) = log(PMT/UPT) - log(PMT/VRM)
                     ^ real trip length      ^ occupancy (ride-sharing)

Trip length is demand geography and scheduling cannot change it. Occupancy is
precisely what a routing and scheduling system determines. So which one moved
decides whether the productivity component of the cost rise is addressable.

CAVEATS, stated up front:
  * Only a minority of demand-response reporters file usable passenger miles in
    both endpoint years, so this is a SUBSAMPLE. Its representativeness is
    measured below, not assumed.
  * NTD passenger miles for demand response are commonly derived from sampling
    rather than counted, so PMT is a softer field than UPT, VRH or VRM.
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
    all_by = defaultdict(dict)
    for r in rows:
        all_by[r["ntd_id"]][r["year"]] = r
    by = defaultdict(dict)
    for r in rows:
        if r["vrm"] > 0 and r["pmt"] > 0:
            by[r["ntd_id"]][r["year"]] = r

    full_ids = [
        n
        for n, y in all_by.items()
        if 2015 in y and 2024 in y and y[2015]["upt"] > 5000 and y[2024]["upt"] > 5000
    ]
    ids = [
        n
        for n, y in by.items()
        if 2015 in y and 2024 in y and y[2015]["upt"] > 5000 and y[2024]["upt"] > 5000
    ]
    say(f"full balanced panel (H5c/H5d):            n = {len(full_ids)}")
    say(f"balanced panel also reporting PASSENGER MILES: n = {len(ids)} "
        f"({100*len(ids)/len(full_ids):.0f}%)")

    # ---- representativeness ---------------------------------------------
    say("\n[0] Is the passenger-miles subsample representative?")
    say(f"  {'':<22}{'PMT subsample':>16}{'rest of panel':>16}")
    rest = [n for n in full_ids if n not in set(ids)]
    for lab, fn in (
        ("median 2024 trips", lambda n: all_by[n][2024]["upt"]),
        ("median 2024 cost/trip", lambda n: all_by[n][2024]["cpt_2024usd"]),
        ("median 2024 trips/hr", lambda n: all_by[n][2024]["trips_per_vrh"]),
        (
            "median real cpt change",
            lambda n: all_by[n][2024]["cpt_2024usd"] / all_by[n][2015]["cpt_2024usd"] - 1,
        ),
    ):
        a, b = median([fn(n) for n in ids]), median([fn(n) for n in rest])
        say(f"  {lab:<22}{a:>16.3f}{b:>16.3f}")
    share_trips = sum(all_by[n][2024]["upt"] for n in ids) / sum(
        all_by[n][2024]["upt"] for n in full_ids
    )
    say(f"  subsample covers {100*share_trips:.1f}% of the balanced panel's 2024 trips")

    def agg(y, num, den):
        return sum(by[n][y][num] for n in ids) / sum(by[n][y][den] for n in ids)

    say("\n[1] The identity, 2015 -> 2024 (n = %d):" % len(ids))
    say(f"  {'quantity':<44}{'2015':>10}{'2024':>10}{'change':>10}")
    out = {"n_subsample": len(ids), "n_full": len(full_ids), "trip_share": share_trips}
    for lab, num, den in (
        ("trips per revenue hour", "upt", "vrh"),
        ("vehicle revenue miles per trip", "vrm", "upt"),
        ("passenger miles per trip (real trip length)", "pmt", "upt"),
        ("occupancy: passenger miles per vehicle mile", "pmt", "vrm"),
        ("average speed (mi/hr)", "vrm", "vrh"),
    ):
        v0, v1 = agg(2015, num, den), agg(2024, num, den)
        say(f"  {lab:<44}{v0:>10.3f}{v1:>10.3f}{100*(v1/v0-1):>9.1f}%")
        out[lab] = {"2015": v0, "2024": v1, "pct": v1 / v0 - 1}

    d_vpt = math.log(agg(2024, "vrm", "upt") / agg(2015, "vrm", "upt"))
    d_len = math.log(agg(2024, "pmt", "upt") / agg(2015, "pmt", "upt"))
    d_occ = math.log(agg(2024, "pmt", "vrm") / agg(2015, "pmt", "vrm"))
    say("\n[2] EXACT split of the rise in vehicle miles per trip:")
    say(f"  D log vehicle mi/trip   = {d_vpt:+.4f}  ({100*(math.exp(d_vpt)-1):+.1f}%)")
    say(
        f"    real TRIP LENGTH      = {d_len:+.4f}  -> {100*d_len/d_vpt:6.1f}%  "
        "(geography; scheduling cannot change it)"
    )
    say(
        f"    lost RIDE-SHARING     = {-d_occ:+.4f}  -> {100*(-d_occ)/d_vpt:6.1f}%  "
        "(occupancy; scheduling sets it)"
    )
    out["split"] = {
        "dlog_vehicle_miles_per_trip": d_vpt,
        "dlog_trip_length": d_len,
        "dlog_occupancy": d_occ,
        "share_trip_length": d_len / d_vpt,
        "share_ridesharing": -d_occ / d_vpt,
    }

    say("\n[3] Per-agency medians (concentration control):")
    per_len = [
        by[n][2024]["pmt"] / by[n][2024]["upt"] / (by[n][2015]["pmt"] / by[n][2015]["upt"]) - 1
        for n in ids
    ]
    per_occ = [
        by[n][2024]["pmt"] / by[n][2024]["vrm"] / (by[n][2015]["pmt"] / by[n][2015]["vrm"]) - 1
        for n in ids
    ]
    say(
        f"  real trip length  median {100*median(per_len):+6.1f}%  "
        f"p25 {100*pct(per_len,25):+6.1f}%  p75 {100*pct(per_len,75):+6.1f}%"
    )
    say(
        f"  occupancy         median {100*median(per_occ):+6.1f}%  "
        f"p25 {100*pct(per_occ,25):+6.1f}%  p75 {100*pct(per_occ,75):+6.1f}%"
    )
    say(f"  agencies whose OCCUPANCY fell: {100*sum(1 for v in per_occ if v<0)/len(per_occ):.1f}%")
    say(f"  agencies whose TRIP LENGTH rose: {100*sum(1 for v in per_len if v>0)/len(per_len):.1f}%")
    out["per_agency"] = {
        "trip_length_median": median(per_len),
        "occupancy_median": median(per_occ),
        "pct_occupancy_fell": sum(1 for v in per_occ if v < 0) / len(per_occ),
        "pct_trip_length_rose": sum(1 for v in per_len if v > 0) / len(per_len),
    }

    say("\n[4] Year by year -- when did ride-sharing break, and has it come back?")
    say(f"  {'year':<6}{'n':>6}{'veh mi/trip':>13}{'pax mi/trip':>13}{'occupancy':>11}{'trips/hr':>10}")
    for y in range(2015, 2025):
        iy = [n for n in by if y in by[n] and by[n][y]["upt"] > 5000]
        u = sum(by[n][y]["upt"] for n in iy)
        m = sum(by[n][y]["vrm"] for n in iy)
        p = sum(by[n][y]["pmt"] for n in iy)
        h = sum(by[n][y]["vrh"] for n in iy)
        say(f"  {y:<6}{len(iy):>6}{m/u:>13.3f}{p/u:>13.3f}{p/m:>11.4f}{u/h:>10.3f}")
        out.setdefault("by_year", {})[y] = {
            "n": len(iy),
            "veh_mi_per_trip": m / u,
            "pax_mi_per_trip": p / u,
            "occupancy": p / m,
            "trips_per_hour": u / h,
        }

    (HERE / "h5e_ridesharing.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    say("\nwrote forge/research/h5e_ridesharing.json")


if __name__ == "__main__":
    main()
