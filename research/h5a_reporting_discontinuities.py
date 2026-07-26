"""H5a -- how much of the sector cost story is a reporting artifact?

Run:  py -3 research/h5a_reporting_discontinuities.py

Not in the brief. Found by sanity-checking H4: MTA New York City Transit reports
demand-response operating expenses of $564.7M in 2023 and $271.6M in 2024 -- a
51.9% fall -- while its DR trips ROSE 4.1% (2.72M -> 2.83M) and its DR vehicle
revenue hours rose 1.6% (2.275M -> 2.311M). Its four other modes all grew opex
that year (HR +7.5%, MB +11.3%, CB +10.7%, RB +12.3%), so this is not an
agency-wide accounting event; it is a restatement of one mode.

NTD is self-reported. If restatements like that are common, then any sector
trend computed from it is partly measuring accounting changes. This script
detects them mechanically and re-runs the headline finding without them.

Detector -- a year is flagged when the money moves and the service does not:
  COST_JUMP     |dlog real opex| > log(1.4)  AND  |dlog VRH| < log(1.10)
  TRIP_RESTATE  |dlog UPT|       > log(2.0)  AND  |dlog VRH| < log(1.10)
Vehicle revenue hours are the hardest quantity in the file to restate (they are
driven by physical vehicle assignments), which is why they are the control.

COVID years are reported separately: 2020 and 2021 saw real service collapse, so
a flag there can be genuine. The screen is most meaningful outside them.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
import sys  # noqa: E402

sys.path.insert(0, str(HERE))
from lib import CPI, median, pct, say  # noqa: E402

COST_JUMP = math.log(1.4)
TRIP_RESTATE = math.log(2.0)
VRH_STABLE = math.log(1.10)


def main() -> None:
    rows = json.loads((HERE / "dr_panel.json").read_text(encoding="utf-8"))
    by = defaultdict(dict)
    for r in rows:
        by[r["ntd_id"]][r["year"]] = r

    flags = []
    transitions = 0
    for nid, yrs in by.items():
        for y in sorted(yrs):
            a, b = yrs.get(y), yrs.get(y + 1)
            if not a or not b:
                continue
            if min(a["vrh"], b["vrh"], a["upt"], b["upt"], a["opex_2024usd"], b["opex_2024usd"]) <= 0:
                continue
            transitions += 1
            d_opex = math.log(b["opex_2024usd"] / a["opex_2024usd"])
            d_upt = math.log(b["upt"] / a["upt"])
            d_vrh = math.log(b["vrh"] / a["vrh"])
            kinds = []
            if abs(d_opex) > COST_JUMP and abs(d_vrh) < VRH_STABLE:
                kinds.append("COST_JUMP")
            if abs(d_upt) > TRIP_RESTATE and abs(d_vrh) < VRH_STABLE:
                kinds.append("TRIP_RESTATE")
            if kinds:
                flags.append(
                    {
                        "ntd_id": nid,
                        "agency": a["agency"],
                        "state": a["state"],
                        "from_year": y,
                        "to_year": y + 1,
                        "kinds": kinds,
                        "dlog_real_opex": d_opex,
                        "dlog_upt": d_upt,
                        "dlog_vrh": d_vrh,
                        "opex_2024usd_from": a["opex_2024usd"],
                        "opex_2024usd_to": b["opex_2024usd"],
                        "upt_from": a["upt"],
                        "upt_to": b["upt"],
                        "cpt_from": a["cpt_2024usd"],
                        "cpt_to": b["cpt_2024usd"],
                    }
                )

    say(f"agency-year transitions examined: {transitions}")
    say(f"flagged: {len(flags)}  ({100*len(flags)/transitions:.1f}%)")
    per_year = defaultdict(int)
    per_kind = defaultdict(int)
    for f in flags:
        per_year[f["to_year"]] += 1
        for k in f["kinds"]:
            per_kind[k] += 1
    say("  by kind: " + ", ".join(f"{k}={v}" for k, v in sorted(per_kind.items())))
    say("  by target year: " + "  ".join(f"{y}:{n}" for y, n in sorted(per_year.items())))
    noncovid = [f for f in flags if f["to_year"] not in (2020, 2021)]
    say(
        f"  excluding COVID target years 2020-21: {len(noncovid)} flags "
        f"({100*len(noncovid)/transitions:.1f}% of transitions)"
    )

    say("\nLargest flagged moves by absolute real-opex change (non-COVID):")
    big = sorted(
        noncovid, key=lambda f: -abs(f["opex_2024usd_to"] - f["opex_2024usd_from"])
    )[:15]
    say(f"  {'agency':<40}{'yrs':>10}{'Dopex%':>9}{'Dupt%':>8}{'Dvrh%':>8}{'$m moved':>10}")
    for f in big:
        say(
            f"  {f['agency'][:39]:<40}{f['from_year']}->{str(f['to_year'])[2:]:>3}"
            f"{100*(math.exp(f['dlog_real_opex'])-1):>9.1f}"
            f"{100*(math.exp(f['dlog_upt'])-1):>8.1f}"
            f"{100*(math.exp(f['dlog_vrh'])-1):>8.1f}"
            f"{(f['opex_2024usd_to']-f['opex_2024usd_from'])/1e6:>10.1f}"
        )

    # ---- the headline, with and without flagged agencies -----------------
    say("\n" + "=" * 74)
    say("Does the sector cost-per-trip story survive dropping flagged agencies?")
    say("=" * 74)

    flagged_ids = {f["ntd_id"] for f in flags}
    say(f"agencies with at least one flag: {len(flagged_ids)} of {len(by)}")

    def headline(exclude: set[str], label: str):
        # BALANCED panel: same agencies present in BOTH 2015 and 2024.
        ids = [
            n
            for n, yrs in by.items()
            if 2015 in yrs and 2024 in yrs and n not in exclude
        ]
        a = {n: by[n][2015] for n in ids}
        b = {n: by[n][2024] for n in ids}
        agg_nom = (
            sum(b[n]["opex_nominal"] for n in ids) / sum(b[n]["upt"] for n in ids)
        ) / (sum(a[n]["opex_nominal"] for n in ids) / sum(a[n]["upt"] for n in ids)) - 1
        agg_real = (
            sum(b[n]["opex_2024usd"] for n in ids) / sum(b[n]["upt"] for n in ids)
        ) / (sum(a[n]["opex_2024usd"] for n in ids) / sum(a[n]["upt"] for n in ids)) - 1
        per_agency = [b[n]["cpt_2024usd"] / a[n]["cpt_2024usd"] - 1 for n in ids]
        # concentration: drop the largest contributor one at a time
        contrib = sorted(ids, key=lambda n: -b[n]["opex_2024usd"])
        drops = []
        for k in (1, 3, 5, 10):
            keep = [n for n in ids if n not in contrib[:k]]
            r = (
                sum(b[n]["opex_2024usd"] for n in keep) / sum(b[n]["upt"] for n in keep)
            ) / (
                sum(a[n]["opex_2024usd"] for n in keep) / sum(a[n]["upt"] for n in keep)
            ) - 1
            drops.append((k, r))
        say(f"\n  {label}: balanced panel n = {len(ids)} agencies (2015 AND 2024)")
        say(f"    aggregate cost/trip change, NOMINAL : {100*agg_nom:+.1f}%")
        say(f"    aggregate cost/trip change, REAL(2024$): {100*agg_real:+.1f}%")
        say(
            f"    per-agency MEDIAN real change: {100*median(per_agency):+.1f}%  "
            f"(p25 {100*pct(per_agency,25):+.1f}%, p75 {100*pct(per_agency,75):+.1f}%)"
        )
        say(
            "    drop-largest-k robustness (real): "
            + "  ".join(f"k={k}:{100*r:+.1f}%" for k, r in drops)
        )
        return {
            "n": len(ids),
            "nominal": agg_nom,
            "real": agg_real,
            "median_per_agency_real": median(per_agency),
            "drop_largest": {str(k): r for k, r in drops},
        }

    full = headline(set(), "ALL agencies")
    clean = headline(flagged_ids, "flagged agencies REMOVED")
    nyct_only = headline({"20008"}, "MTA NYCT removed only")

    out = {
        "detector": {
            "cost_jump_log": COST_JUMP,
            "trip_restate_log": TRIP_RESTATE,
            "vrh_stable_log": VRH_STABLE,
        },
        "transitions": transitions,
        "n_flags": len(flags),
        "n_flags_ex_covid": len(noncovid),
        "flags_by_year": dict(per_year),
        "flags_by_kind": dict(per_kind),
        "headline_all": full,
        "headline_flagged_removed": clean,
        "headline_nyct_removed": nyct_only,
        "flags": flags,
    }
    (HERE / "h5a_reporting_discontinuities.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )
    say("\nwrote research/h5a_reporting_discontinuities.json")


if __name__ == "__main__":
    main()
