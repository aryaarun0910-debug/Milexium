"""Build a contact-research worksheet for design-partner outreach.

The cold email is written (generate_design_partner_emails.py) and personalized
with each agency's own NTD deadhead-dollar figure. The one thing the NTD data
CANNOT give us is a human to send it to: the ops / mobility / paratransit
manager's name and email. That is the genuinely manual, human part - LinkedIn
plus agency websites - and this worksheet exists to make it as fast as possible.

It emits one row per target agency, pre-filled with everything we already know
(the agency, its real NTD numbers, the ready-to-paste hook sentence, and
click-to-research URLs), and BLANK columns for the contact name / title /
email / LinkedIn / website you fill in by hand. Work it top-down: the rows are
ranked by deadhead dollars, so the biggest hooks come first.

Target selection follows design_partner_pitch.md exactly: the mid-size sweet
spot, NOT the mega-metros. Roughly 50k-300k annual demand-response trips with
deadhead over 15% - big enough that the savings are real money, small enough
that an ops director can say yes to a pilot without a procurement gauntlet.

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

# The sweet spot from design_partner_pitch.md: mid-size, real deadhead, not metros.
MIN_TRIPS, MAX_TRIPS = 50_000, 300_000
MIN_DEADHEAD = 0.15

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


def email_hook(r) -> str:
    """The exact personalized sentence from the cold email - paste-ready once a
    name is filled in, so the worksheet and the draft always show the same
    number in front of a director who knows their own books."""
    trips = f"{r.trips:,.0f}"
    cpt = f"${r.cost_per_trip:,.2f}"
    dh = f"{r.deadhead_pct_hours:.0%}"
    val = f"${r.value_10pct_deadhead_cut:,.0f}"
    return (f"Your agency's 2024 NTD filing shows {trips} demand-response trips "
            f"at {cpt} per trip, with {dh} of vehicle-hours spent deadheading. "
            f"If that's roughly right, cutting deadhead by 10 percent is worth "
            f"about {val} a year to you.")


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
    args = ap.parse_args()

    df = pd.read_csv(HERE.parent / "ntd" / "agency_economics.csv",
                     dtype={"ntd_id": str})
    df = df[df.report_year == 2024].copy()
    df = df[(df.trips >= MIN_TRIPS) & (df.trips <= MAX_TRIPS)
            & (df.deadhead_pct_hours >= MIN_DEADHEAD)
            & (df.value_10pct_deadhead_cut > 0)]
    if not args.include_metros:
        metro = df.agency.str.contains(
            "|".join(re.escape(m) for m in BIG_CITY_METROS), case=False)
        df = df[~metro]
    if args.state:
        df = df[df.state == args.state.upper()]
    df = df.sort_values("value_10pct_deadhead_cut", ascending=False)
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
            "deadhead_dollars_per_yr": round(r.value_10pct_deadhead_cut),
            "deadhead_pct": round(r.deadhead_pct_hours, 3),
            "annual_dr_trips": int(r.trips),
            "cost_per_trip": round(r.cost_per_trip, 2),
            "vehicles": r.vehicles,
            "org_type": r.organization_type,
            "email_hook": email_hook(r),
            # --- your notes ---
            "notes": "",
        })

    out = pd.DataFrame(rows)
    out.to_csv(OUTFILE, index=False)
    print(f"wrote {len(out)} target rows to {OUTFILE}")
    print(f"pool: {MIN_TRIPS:,}-{MAX_TRIPS:,} DR trips, deadhead >= "
          f"{MIN_DEADHEAD:.0%}" + (f", state={args.state.upper()}" if args.state else ""))
    if len(out):
        preview = out[["priority", "short_name", "state",
                       "deadhead_dollars_per_yr", "org_fit"]].head(12)
        print(preview.to_string(index=False))
    print("\nFill contact_name / contact_email / linkedin_url per row, then a "
          "fresh session with the Gmail connector turns these into drafts.")
