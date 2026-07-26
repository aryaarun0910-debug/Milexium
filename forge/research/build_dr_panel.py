"""Build the demand-response agency-year panel, 2015-2024, from OPEX.

One row per (ntd_id, report_year), summing across Type of Service (DO/PT/TX/TN)
within Mode='DR'. Money is carried nominal AND deflated to 2024 dollars.

Also carries, per agency-year, the agency's ALL-MODE trips so that DR mode share
is computable -- which is what lets any downstream claim satisfy the
`mode_provenance` check rather than assert it.

Writes forge/research/dr_panel.json.
"""

from __future__ import annotations

import json
from collections import defaultdict

from lib import REPO, load_opex_panel, say, to_2024_dollars

FIELDS = {
    "Operating Expenses": "opex",
    "Fares": "fares",
    "Unlinked Passenger Trips": "upt",
    "Vehicle Revenue Hours": "vrh",
    "Vehicle Revenue Miles": "vrm",
    "Vehicles Operated in Maximum Service": "voms",
    "Passenger Miles Traveled": "pmt",
    "Operating Expenses - Vehicle Operations": "opex_ops",
    "Operating Expenses - Vehicle Maintenance": "opex_maint",
    "Operating Expenses - General Administration": "opex_admin",
    "Operating Expenses - Facility Maintenance": "opex_fac",
}


def main() -> None:
    loaded = load_opex_panel()
    panel, meta = loaded["panel"], loaded["meta"]

    dr = defaultdict(lambda: defaultdict(float))
    allmode = defaultdict(lambda: defaultdict(float))
    tos_upt = defaultdict(lambda: defaultdict(float))

    for (nid, year, mode, tos), fields in panel.items():
        for src, dst in FIELDS.items():
            v = fields.get(src)
            if v is None:
                continue
            allmode[(nid, year)][dst] += v
            if mode == "DR":
                dr[(nid, year)][dst] += v
                if dst == "upt":
                    tos_upt[(nid, year)][tos] += v

    rows = []
    for (nid, year), f in sorted(dr.items()):
        upt, vrh, opex = f.get("upt", 0), f.get("vrh", 0), f.get("opex", 0)
        if upt <= 0 or vrh <= 0 or opex <= 0:
            continue
        am = allmode[(nid, year)]
        m = meta.get(nid, {})
        try:
            uzapop = float(m.get("uza_population") or 0)
        except ValueError:
            uzapop = 0.0
        tx = tos_upt[(nid, year)]
        rows.append(
            {
                "ntd_id": nid,
                "year": year,
                "agency": m.get("agency", ""),
                "state": m.get("state", ""),
                "uza_name": m.get("uza_name", ""),
                "uza_population": uzapop,
                "reporter_type": m.get("reporter_type", ""),
                "upt": upt,
                "vrh": vrh,
                "vrm": f.get("vrm", 0),
                "voms": f.get("voms", 0),
                "pmt": f.get("pmt", 0),
                "opex_nominal": opex,
                "opex_2024usd": to_2024_dollars(opex, year),
                "fares_nominal": f.get("fares", 0),
                "opex_ops": f.get("opex_ops", 0),
                "opex_admin": f.get("opex_admin", 0),
                "opex_maint": f.get("opex_maint", 0),
                # derived
                "cpt_nominal": opex / upt,
                "cpt_2024usd": to_2024_dollars(opex, year) / upt,
                "trips_per_vrh": upt / vrh,
                "cost_per_vrh_2024usd": to_2024_dollars(opex, year) / vrh,
                "miles_per_hour": (f.get("vrm", 0) / vrh) if vrh else 0.0,
                "farebox_recovery": (f.get("fares", 0) / opex) if opex else 0.0,
                "admin_share": (f.get("opex_admin", 0) / opex) if opex else 0.0,
                # mode provenance: what share of this agency's trips are DR?
                "dr_share_of_agency_upt": (upt / am["upt"]) if am.get("upt") else None,
                "agency_allmode_upt": am.get("upt", 0),
                # purchased/taxi/TNC share WITHIN demand response
                "pt_share_of_dr_upt": (tx.get("PT", 0) / upt) if upt else 0.0,
                "do_share_of_dr_upt": (tx.get("DO", 0) / upt) if upt else 0.0,
                "taxi_tnc_share_of_dr_upt": (
                    (tx.get("TX", 0) + tx.get("TN", 0)) / upt if upt else 0.0
                ),
            }
        )

    out = REPO / "forge" / "research" / "dr_panel.json"
    out.write_text(json.dumps(rows), encoding="utf-8")
    say(f"DR agency-years: {len(rows)}")
    say(f"distinct agencies: {len({r['ntd_id'] for r in rows})}")
    yrs = defaultdict(int)
    for r in rows:
        yrs[r["year"]] += 1
    say("per year: " + "  ".join(f"{y}:{n}" for y, n in sorted(yrs.items())))
    say(f"wrote {out}")


if __name__ == "__main__":
    main()
