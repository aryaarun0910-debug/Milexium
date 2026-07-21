"""Self-serve, public-data-only savings calculator.

Backend logic for the "punch in your agency, see your own numbers" widget
planned for the website (Arya + Chris, website phase). Deliberately built
now, ahead of the site, because it reuses ntd/agency_economics.csv directly
and needs no PHI, no routing demo, no map: every number here is the
agency's own public NTD filing, run through transparent arithmetic. This
is the artifact that lets a cold agency contact or a YC reader get a
personalized result with zero call booked.

Two entry points:
- find_agency(query): fuzzy name/city/state search over the NTD table
- compute_savings(ntd_id, deadhead_cut_pcts): the actual calculator

CLI:
  py -3 ntd/savings_calculator.py "Access Services"
  py -3 ntd/savings_calculator.py --state CA --top 5
"""

import argparse
import json
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
_DF = None


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


def compute_savings(ntd_id: str, deadhead_cut_pcts=(0.05, 0.10, 0.20)) -> dict:
    """The calculator: every figure traces to the agency's own NTD filing.

    If the agency reports deadhead detail (413 of 1,968 do), the primary
    hook is dollar value of a deadhead cut. Otherwise, fall back to a
    cost-per-trip gap versus the national median, phrased as an efficiency
    opportunity rather than a specific mechanism (we do not know THEIR
    deadhead rate, so we do not imply we do).
    """
    df = _load()
    row = df[df.ntd_id.astype(str).str.zfill(5) == str(ntd_id).zfill(5)]
    if row.empty:
        raise ValueError(f"no agency with NTD id {ntd_id}")
    r = row.iloc[0]
    median_cpt = float(df[df.report_year == 2024].cost_per_trip.median())

    result = {
        "ntd_id": r.ntd_id, "agency": r.agency, "city": r.city,
        "state": r.state, "report_year": int(r.report_year),
        "source": "FTA National Transit Database, agency's own annual filing",
        "annual_trips": int(r.trips),
        "annual_operating_expense": round(float(r.opex), 0),
        "cost_per_trip": round(float(r.cost_per_trip), 2),
        "national_median_cost_per_trip_2024": round(median_cpt, 2),
        "vehicles": int(r.vehicles) if pd.notna(r.vehicles) else None,
        "has_deadhead_detail": bool(pd.notna(r.deadhead_pct_hours)),
    }

    if result["has_deadhead_detail"]:
        result["deadhead_pct_of_hours"] = round(float(r.deadhead_pct_hours), 4)
        result["scenarios"] = [
            {
                "deadhead_cut_pct": pct,
                "annual_dollar_value": round(
                    pct * float(r.deadhead_cost), 0),
            }
            for pct in deadhead_cut_pcts
        ]
        best = result["scenarios"][-1]
        result["headline"] = (
            f"{r.agency} reported {r.trips:,.0f} demand-response trips at "
            f"${r.cost_per_trip:,.2f} per trip in its {int(r.report_year)} "
            f"NTD filing, with {r.deadhead_pct_hours:.0%} of vehicle hours "
            f"spent deadheading. Cutting that by {best['deadhead_cut_pct']:.0%} "
            f"is worth about ${best['annual_dollar_value']:,.0f} a year, "
            f"straight from your own reported numbers.")
    else:
        gap = float(r.cost_per_trip) - median_cpt
        result["cost_per_trip_gap_vs_median"] = round(gap, 2)
        result["scenarios"] = [
            {"gap_closed_pct": pct,
             "annual_dollar_value": round(
                 max(gap, 0) * pct * float(r.trips), 0)}
            for pct in deadhead_cut_pcts
        ] if gap > 0 else []
        if gap > 0:
            best = result["scenarios"][-1]
            result["headline"] = (
                f"{r.agency} reported {r.trips:,.0f} trips at "
                f"${r.cost_per_trip:,.2f} per trip, versus a national median "
                f"of ${median_cpt:,.2f}. Closing {best['gap_closed_pct']:.0%} "
                f"of that gap is worth about ${best['annual_dollar_value']:,.0f} "
                f"a year.")
        else:
            result["headline"] = (
                f"{r.agency} already runs at ${r.cost_per_trip:,.2f} per "
                f"trip, leaner than the ${median_cpt:,.2f} national median. "
                f"We'd like to learn what you do well and show you where "
                f"trip-level explanations still save hours of dispute "
                f"handling.")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("query", nargs="?", help="agency name, city, or state")
    ap.add_argument("--state", help="filter to a state abbreviation")
    ap.add_argument("--top", type=int, default=1,
                     help="show top N matches instead of computing one")
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
            result = compute_savings(matches[0]["ntd_id"])
            print(json.dumps(result, indent=2))
            print()
            print(result["headline"])
