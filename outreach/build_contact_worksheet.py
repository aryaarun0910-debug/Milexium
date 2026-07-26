"""Build a contact-research worksheet for design-partner outreach.

The cold email is written (generate_design_partner_emails.py) and personalized
with the agency's own NTD numbers and its position in the national panel. The
one thing the NTD data CANNOT give us is a human to send it to: the ops /
mobility / paratransit manager's name and email. That is the genuinely manual,
human part - LinkedIn plus agency websites - and this worksheet exists to make
it as fast as possible.

It emits one row per target agency, pre-filled with everything we already know
(the agency, its real NTD numbers, the ready-to-paste hook sentence, and
click-to-research URLs), and BLANK columns for the contact name / title /
email / LinkedIn / website you fill in by hand. Work it top-down: the rows are
ranked by cost-per-trip percentile, so the operators furthest from the
national middle come first.

TARGETING AND THE HOOK NO LONGER USE DEADHEAD
---------------------------------------------
This file used to select on `deadhead_pct_hours >= 0.15` ("big enough that the
savings are real money"), rank on `value_10pct_deadhead_cut`, and write a
hedged dollar estimate of a 10 percent deadhead cut into every hook. All three
are removed (packet MX-CLAIMS-DOLLAR-SWEEP-013). Deadhead share does not
identify an expensive agency - Pearson +0.017, OLS R2 0.0003 on n=405
(research/h5b_structure_vs_cost.json); Spearman +0.024 over 406 operators
against +0.738 for cost per HOUR, with cost per trip flat at $48.53 in the
lowest deadhead quartile against $54.09 in the highest
(outreach/panel_findings.json, `dr_deadhead_predicts_cost_per_trip`, REJECTED
by the panel gate) - so selecting on it selected on noise, and pricing it sold
a recovery nobody has measured.

Selection is now size band plus cost per trip at or above the national median:
cost per trip is the outcome itself rather than a proxy for it, it varies 5.0x
across US operators (`dr_cost_per_trip_dispersion_2024`, gate-passed), and
being above the median is a fact about the filing rather than a diagnosis.

NOTE FOR WHOEVER RUNS THIS NEXT: the live worksheet was built under the OLD
criteria, so a regeneration will not reproduce the same 109 agencies. That is
intended - the old pool was selected on a signal now known to be flat - but it
means the existing hand-researched contacts must be carried over, not blown
away. The --force guard below exists for exactly this.

Output: outreach/contact_research_worksheet.csv

Usage:
  py -3 outreach/build_contact_worksheet.py              # all qualifying rows
  py -3 outreach/build_contact_worksheet.py --top 15     # just the first batch
  py -3 outreach/build_contact_worksheet.py --state PA   # cluster one state
"""

import argparse
import re
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd

HERE = Path(__file__).parent
OUTFILE = HERE / "contact_research_worksheet.csv"

# The sweet spot from design_partner_pitch.md: mid-size, not metros.
MIN_TRIPS, MAX_TRIPS = 50_000, 300_000
# At or above the national median cost per trip. Not a diagnosis - half the
# panel is above the median by construction - just the half where the question
# "which of the two things underneath this is yours?" is worth asking.
MIN_COST_PER_TRIP_PERCENTILE = 50.0

# A couple of big-city agencies slip under the 300k-trip cap because their
# paratransit arm is mid-sized even though the parent runs a massive multimodal
# system with exactly the procurement layers design_partner_pitch.md warns
# against. Dropped by default so the top of the sheet is actionable; pass
# --include-metros to keep them. Substring match on the legal name; edit freely.
BIG_CITY_METROS = (
    "San Francisco Municipal Transportation",
    "City of Los Angeles",
)

# Why each org type is an easy pilot yes (they pick their own software; no
# state-DOT procurement gauntlet). Falls back to the raw type if unmapped.
ORG_FIT = {
    "Private-Non-Profit Corporation": "Non-profit - picks its own software",
    "Independent Public Agency or Authority of Transit Service":
        "Regional authority - picks its own software",
    "City, County or Local Government Unit or Department of Transportation":
        "County/local govt - ops director can pilot",
    "Area Agency on Aging": "Agency on Aging - mobility is the mission",
    "MPO, COG or Other Planning Agency": "Planning agency / COG",
    "Tribe": "Tribal transit",
}


def short_agency(name: str) -> str:
    """The trade name staff actually use (dba:), else the legal name trimmed."""
    m = re.search(r"dba:\s*(.+)$", name, flags=re.I)
    if m:
        return m.group(1).strip()
    return re.sub(r",?\s*(Inc\.|Corporation|Authority|Department).*$", "",
                  name).strip() or name


def email_hook(r, panel) -> str:
    """The exact opening paragraph of the cold email - paste-ready once a name
    is filled in, so the worksheet preview and the sent draft always match.

    Carries NO dollar figure. Every number in it is either the agency's own
    filed figure or its rank within the same year's national panel, so an ops
    director who knows their own books can check all of it and none of it
    asserts a recovery. The previous version priced a hypothetical 10 percent
    deadhead cut; see the module docstring for why that is gone.
    """
    pct = pctile(panel.cost_per_trip, r.cost_per_trip)
    return (f"Your agency's 2024 NTD filing reports {r.trips:,.0f} "
            f"demand-response trips at ${r.cost_per_trip:,.2f} per trip. "
            f"Against the {len(panel):,} US operators filing demand-response "
            f"service that year that puts you at percentile {pct:.0f}, and the "
            f"two numbers underneath it are ${r.cost_per_vrh:,.2f} per revenue "
            f"hour (national median ${panel.cost_per_vrh.median():,.2f}) and "
            f"{r.trips_per_vrh:,.2f} trips per revenue hour (median "
            f"{panel.trips_per_vrh.median():,.2f}). Nationally about half the "
            f"spread in cost per trip is the price of an hour and about half is "
            f"how many trips fit into one, and only the second is anything a "
            f"scheduler sets - which of those two is yours is the thing we "
            f"can't tell from the outside.")


def pctile(series, value) -> float:
    """Percentile of one operator within the national panel for a metric."""
    s = series.dropna()
    return float((s < value).mean() * 100)


def google_url(r) -> str:
    q = f'"{short_agency(r.agency)}" {r.city} {r.state} paratransit mobility manager'
    return f"https://www.google.com/search?q={quote_plus(q)}"


def linkedin_url(r) -> str:
    q = f"{short_agency(r.agency)} mobility OR paratransit manager"
    return f"https://www.linkedin.com/search/results/people/?keywords={quote_plus(q)}"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", type=int, help="keep only the first N rows")
    ap.add_argument("--state", help="filter to a state abbreviation (e.g. PA)")
    ap.add_argument("--include-metros", action="store_true",
                    help="keep the big-city metros dropped by default")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing worksheet even if it already "
                         "has filled-in contacts (default: refuse, to protect "
                         "hand-entered research)")
    args = ap.parse_args()

    # Guard: never silently destroy hand-entered contact research. If the
    # worksheet already exists with any filled contact_email, refuse to
    # regenerate it (which would blank every row) unless --force. Add new
    # targets by hand or to a copy; do not regenerate over live research.
    if OUTFILE.exists() and not args.force:
        existing = pd.read_csv(OUTFILE)
        if "contact_email" in existing.columns:
            filled = (existing["contact_email"].notna()
                      & (existing["contact_email"].astype(str).str.strip() != "")
                      & (existing["contact_email"].astype(str) != "nan"))
            if filled.any():
                raise SystemExit(
                    f"REFUSING to overwrite {OUTFILE.name}: it already has "
                    f"{int(filled.sum())} filled contact(s). Regenerating would "
                    f"blank your research. Use --force only if you're sure, or "
                    f"back the file up first.")

    econ = pd.read_csv(HERE.parent / "ntd" / "agency_economics.csv",
                       dtype={"ntd_id": str})
    # The comparison panel is every 2024 filer and is taken BEFORE the
    # targeting filter, so a percentile quoted to an operator is national.
    panel = econ[econ.report_year == 2024].copy()
    cpt_floor = panel.cost_per_trip.quantile(MIN_COST_PER_TRIP_PERCENTILE / 100)
    df = panel[(panel.trips >= MIN_TRIPS) & (panel.trips <= MAX_TRIPS)
               & (panel.cost_per_trip >= cpt_floor)
               & panel.cost_per_vrh.notna() & panel.trips_per_vrh.notna()]
    if not args.include_metros:
        metro = df.agency.str.contains(
            "|".join(re.escape(m) for m in BIG_CITY_METROS), case=False)
        df = df[~metro]
    if args.state:
        df = df[df.state == args.state.upper()]
    df = df.sort_values("cost_per_trip", ascending=False)
    if args.top:
        df = df.head(args.top)

    rows = []
    for i, r in enumerate(df.itertuples(), start=1):
        rows.append({
            # --- ranked identity (pre-filled, don't touch) ---
            "priority": i,
            "agency": r.agency,
            "short_name": short_agency(r.agency),
            "city": r.city,
            "state": r.state,
            "org_fit": ORG_FIT.get(r.organization_type, r.organization_type),
            # --- click these to do the research ---
            "google_search": google_url(r),
            "linkedin_search": linkedin_url(r),
            # --- FILL THESE IN (the manual, human part) ---
            "contact_name": "",
            "contact_title": "",
            "contact_email": "",
            "linkedin_url": "",
            "website": "",
            "phone": "",
            "status": "to research",
            # --- the hook numbers, for reference (pre-filled) ---
            # No dollar column. `deadhead_pct` stays because it is a figure the
            # agency itself filed, but it is reference only: it does not select
            # targets, rank them, or appear in the hook.
            "cost_per_trip": round(r.cost_per_trip, 2),
            "cost_per_trip_pctile": round(
                pctile(panel.cost_per_trip, r.cost_per_trip)),
            "cost_per_vrh": round(r.cost_per_vrh, 2),
            "trips_per_vrh": round(r.trips_per_vrh, 2),
            "deadhead_pct": (round(r.deadhead_pct_hours, 3)
                             if pd.notna(r.deadhead_pct_hours) else ""),
            "annual_dr_trips": int(r.trips),
            "vehicles": r.vehicles,
            "org_type": r.organization_type,
            "email_hook": email_hook(r, panel),
            # --- your notes ---
            "notes": "",
        })

    out = pd.DataFrame(rows)
    out.to_csv(OUTFILE, index=False)
    print(f"wrote {len(out)} target rows to {OUTFILE}")
    print(f"pool: {MIN_TRIPS:,}-{MAX_TRIPS:,} DR trips, cost per trip >= "
          f"${cpt_floor:,.2f} (national percentile "
          f"{MIN_COST_PER_TRIP_PERCENTILE:.0f} of {len(panel):,} 2024 filers)"
          + (f", state={args.state.upper()}" if args.state else ""))
    if len(out):
        preview = out[["priority", "short_name", "state", "cost_per_trip",
                       "cost_per_trip_pctile", "org_fit"]].head(12)
        print(preview.to_string(index=False))
    print("\nFill contact_name / contact_email / linkedin_url per row, then a "
          "fresh session with the Gmail connector turns these into drafts.")
