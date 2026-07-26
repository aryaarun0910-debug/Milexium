"""Self-serve, public-data-only PEER POSITION lookup.

Backend logic for the "punch in your agency, see your own numbers" widget
planned for the website. Every number here is the agency's own public NTD
filing, run through transparent arithmetic, and every comparison is against
the national demand-response panel from the same filings. No PHI, no routing
demo, no map, no call booked.

WHAT THIS TOOL WILL NOT DO, AND WHY
-----------------------------------
This module used to be ntd/savings_calculator.py and its centre was
``compute_savings(ntd_id, deadhead_cut_pcts)``, which handed any agency a
personalised annual dollar figure for a hypothetical deadhead cut, or failing
that for closing a fraction of its cost-per-trip gap to the national median.
BOTH FUNCTIONS HAVE BEEN REMOVED (packet MX-CLAIMS-DOLLAR-SWEEP-013), not
softened, because their entire purpose was to produce a number the data does
not support:

- Deadhead share does not identify an expensive agency. Pearson +0.017, OLS
  R2 0.0003 on n=405 (research/h5b_structure_vs_cost.json). Spearman +0.024
  over 406 operators against +0.738 for cost per HOUR, and cost per trip is
  flat across deadhead quartiles -- $48.53 in the LOWEST deadhead quartile
  against $54.09 in the highest (outreach/panel_findings.json, finding
  `dr_deadhead_predicts_cost_per_trip`, REJECTED by the panel gate).
- The cost-per-trip gap to the median is not known to be recoverable. Treating
  it as recoverable is a causal claim, and it is precisely the claim the rest
  of the platform refuses to make: packages/replay/teardown.py will not emit a
  savings envelope without the operator's own fixed/variable cost split, and
  public copy does not get a lower standard than code.

A public tool that hands an agency an unsupported savings number is the single
most damaging artifact this repo could ship, so it does not ship.

WHAT IT DOES INSTEAD
--------------------
Position. Where an operator sits against the national panel on cost per trip,
on productivity (trips per vehicle revenue hour) and on cost per revenue hour
is computable, checkable by the operator against its own books, and genuinely
new information -- an operator cannot see its own national rank from inside
its own data. It makes no claim about what any intervention would recover.

Cost per revenue hour is the position worth reading first: it ranks with cost
per trip at Spearman +0.738, where deadhead share ranks at +0.024.

Two entry points:
- find_agency(query): fuzzy name/city/state search over the NTD table
- compare_agency(ntd_id): national position on the three comparison metrics,
  plus the deadhead accounting identity, explicitly labelled as one

CLI:
  py -3 ntd/peer_position.py "Access Services"
  py -3 ntd/peer_position.py --state CA --top 5
"""

import argparse
import json
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
PANEL_YEAR = 2024
_DF = None

# Wording that must travel with the deadhead dollar figure wherever it is
# rendered. The figure is arithmetic on the agency's own filing; the share of
# it that is recoverable is unknown and this tool does not model it.
DEADHEAD_IDENTITY_NOTE = (
    "Accounting identity, not a saving: this is what those empty vehicle-hours "
    "cost at your own reported average cost per hour. How much of it is "
    "recoverable is unknown -- fixed costs do not fall with utilisation, and "
    "that depends on your own fixed-versus-variable split, which is not in any "
    "public filing. Deadhead share also does not predict cost per trip "
    "(Spearman +0.024 across 406 operators), so a high figure here is a "
    "description of your hours, not a diagnosis of your costs."
)


def _load() -> pd.DataFrame:
    global _DF
    if _DF is None:
        _DF = pd.read_csv(HERE / "agency_economics.csv", dtype={"ntd_id": str})
    return _DF


def _score(query: str, row: pd.Series) -> float:
    q = query.lower()
    fields = [str(row.agency), str(row.city), str(row.state)]
    return max(SequenceMatcher(None, q, f.lower()).ratio() for f in fields)


def find_agency(query: str, limit: int = 5) -> list[dict]:
    """Fuzzy-match an agency by name, city, or state abbreviation."""
    df = _load()
    scored = df.copy()
    scored["match_score"] = scored.apply(lambda r: _score(query, r), axis=1)
    # exact substring hits always float to the top regardless of fuzzy score
    substr = scored.agency.str.lower().str.contains(query.lower(), regex=False)
    scored.loc[substr, "match_score"] = 1.0
    top = scored.sort_values("match_score", ascending=False).head(limit)
    return top[["ntd_id", "agency", "city", "state", "report_year", "trips",
                "cost_per_trip", "match_score"]].to_dict("records")


def _position(panel: pd.Series, value: float, higher_is_better: bool) -> dict:
    """Where one operator sits in the national distribution of one metric."""
    s = panel.dropna()
    pctile = float((s < value).mean() * 100)
    return {
        "value": round(float(value), 2),
        "national_p10": round(float(s.quantile(0.10)), 2),
        "national_median": round(float(s.median()), 2),
        "national_p90": round(float(s.quantile(0.90)), 2),
        "percentile": round(pctile, 0),
        "n_operators": int(len(s)),
        # plain-English direction, so a renderer cannot invert it by accident
        "reads_as": ("higher is more productive" if higher_is_better
                     else "higher is more expensive"),
    }


def compare_agency(ntd_id: str) -> dict:
    """National position for one agency. No savings figure is produced.

    Every field traces to the agency's own NTD filing or to the same-year
    national panel in ntd/agency_economics.csv.
    """
    df = _load()
    row = df[df.ntd_id.astype(str).str.zfill(5) == str(ntd_id).zfill(5)]
    if row.empty:
        raise ValueError(f"no agency with NTD id {ntd_id}")
    r = row.iloc[0]
    panel = df[df.report_year == PANEL_YEAR]

    result = {
        "ntd_id": r.ntd_id, "agency": r.agency, "city": r.city,
        "state": r.state, "report_year": int(r.report_year),
        "source": "FTA National Transit Database, agency's own annual filing",
        "comparison_panel": (
            f"{len(panel):,} US demand-response operators, NTD report year "
            f"{PANEL_YEAR}"),
        "status": "Demonstrated, never Validated - this describes what was "
                  "FILED; no operator has confirmed it against their books",
        "annual_trips": int(r.trips),
        "annual_operating_expense": round(float(r.opex), 0),
        "vehicles": int(r.vehicles) if pd.notna(r.vehicles) else None,
        "position": {
            "cost_per_trip": _position(
                panel.cost_per_trip, r.cost_per_trip, higher_is_better=False),
            "cost_per_revenue_hour": _position(
                panel.cost_per_vrh, r.cost_per_vrh, higher_is_better=False),
            "trips_per_revenue_hour": _position(
                panel.trips_per_vrh, r.trips_per_vrh, higher_is_better=True),
        },
        "read_this_one_first": (
            "cost_per_revenue_hour -- across 406 operators it ranks with cost "
            "per trip at Spearman +0.738, where deadhead share ranks at +0.024 "
            "(outreach/panel_findings.json)"),
        "has_deadhead_detail": bool(pd.notna(r.deadhead_pct_hours)),
    }

    if result["has_deadhead_detail"]:
        result["deadhead"] = {
            "pct_of_vehicle_hours": round(float(r.deadhead_pct_hours), 4),
            "national_median_pct": round(
                float(panel.deadhead_pct_hours.median()), 4),
            "annual_cost_accounting_identity_usd": round(
                float(r.deadhead_cost), 0),
            "identity": "opex * deadhead_hours / actual_total_hours",
            "note": DEADHEAD_IDENTITY_NOTE,
            "is_a_saving": False,
        }

    cpt = result["position"]["cost_per_trip"]
    tph = result["position"]["trips_per_revenue_hour"]
    cph = result["position"]["cost_per_revenue_hour"]
    result["headline"] = (
        f"{r.agency} reported {r.trips:,.0f} demand-response trips in its "
        f"{int(r.report_year)} NTD filing at ${r.cost_per_trip:,.2f} per trip "
        f"(percentile {cpt['percentile']:.0f} nationally, median "
        f"${cpt['national_median']:,.2f}), ${r.cost_per_vrh:,.2f} per revenue "
        f"hour (percentile {cph['percentile']:.0f}, median "
        f"${cph['national_median']:,.2f}) and {r.trips_per_vrh:,.2f} trips per "
        f"revenue hour (percentile {tph['percentile']:.0f}, median "
        f"{tph['national_median']:,.2f}). That is a position, not a problem: "
        f"what it costs to move somebody depends on the price of an hour and "
        f"on how many trips fit into one, and roughly half the national "
        f"variation is each.")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("query", nargs="?", help="agency name, city, or state")
    ap.add_argument("--state", help="filter to a state abbreviation")
    ap.add_argument("--top", type=int, default=1,
                     help="show top N matches instead of comparing one")
    args = ap.parse_args()

    if args.state and not args.query:
        df = _load()
        rows = (df[df.state == args.state.upper()]
                .sort_values("trips", ascending=False).head(args.top))
        print(rows[["agency", "city", "trips", "cost_per_trip"]]
              .to_string(index=False))
    elif args.top > 1:
        for m in find_agency(args.query, limit=args.top):
            print(f"{m['ntd_id']}  {m['agency']} ({m['city']}, {m['state']}) "
                  f"- {m['trips']:,.0f} trips, ${m['cost_per_trip']:.2f}/trip")
    else:
        matches = find_agency(args.query, limit=1)
        if not matches:
            print(f"no match for {args.query!r}")
        else:
            result = compare_agency(matches[0]["ntd_id"])
            print(json.dumps(result, indent=2))
            print()
            print(result["headline"])
