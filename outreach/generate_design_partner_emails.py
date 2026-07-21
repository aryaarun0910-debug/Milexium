"""Generate personalized design-partner outreach emails from NTD economics.

The moat-building motion: you don't buy a data moat, you earn it by getting
an operator to hand you their trip data. That starts with a cold email that
leads with THEIR money (their own NTD-reported deadhead cost), not with "I'm
a student." The personalized number is the pattern-interrupt that gets the
15-minute call; the design-partner / free-analysis offer (see
design_partner_pitch.md) is made on that call.

Reads ntd/agency_economics.csv (every agency's own filing) and emits one
ready-to-send email per target: subject + body, under ~120 words, leading
with the agency's specific deadhead-dollar figure.

Output: outreach/drafts/<state>_<agency_slug>.txt  (subject on line 1,
blank line, then body) - ready to paste into a Gmail draft, or to feed to
the Gmail draft connector once it's authorized.

Usage:
  py -3 outreach/generate_design_partner_emails.py            # top 40 by savings
  py -3 outreach/generate_design_partner_emails.py --top 100
  py -3 outreach/generate_design_partner_emails.py --state PA # one state
"""

import argparse
import re
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
DRAFTS = HERE / "drafts"
DRAFTS.mkdir(exist_ok=True)

# Fill these in once; they're the same across every email.
SENDER = "Arya"
SIGNOFF_CONTACT = "[your@domain email]  ·  [link to site or one-pager]"


def slug(s: str) -> str:
    s = re.sub(r",?\s*dba:.*$", "", s, flags=re.I)  # drop "dba: ..." tail
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return s[:50]


def short_agency(name: str) -> str:
    # Prefer the "dba:" trade name if present (what staff actually call it)
    m = re.search(r"dba:\s*(.+)$", name, flags=re.I)
    if m:
        return m.group(1).strip()
    return re.sub(r",?\s*(Inc\.|Corporation|Authority|Department).*$", "",
                  name).strip() or name


def email_for(r) -> tuple[str, str]:
    agency = short_agency(r.agency)
    trips = f"{r.trips:,.0f}"
    cpt = f"${r.cost_per_trip:,.2f}"

    if pd.notna(r.deadhead_pct_hours) and pd.notna(r.value_10pct_deadhead_cut) \
            and r.value_10pct_deadhead_cut > 0:
        dh = f"{r.deadhead_pct_hours:.0%}"
        val = f"${r.value_10pct_deadhead_cut:,.0f}"
        subject = f"{agency}: a {val}/yr question about your paratransit deadhead"
        hook = (f"Your agency's 2024 NTD filing shows {trips} demand-response "
                f"trips at {cpt} per trip, with {dh} of vehicle-hours spent "
                f"deadheading. If that's roughly right, cutting deadhead by "
                f"10 percent is worth about {val} a year to you.")
    else:
        subject = f"{agency}: a question about your paratransit cost per trip"
        hook = (f"Your agency's 2024 NTD filing shows {trips} demand-response "
                f"trips at {cpt} per trip. We pulled every US agency's numbers "
                f"and yours stood out enough that we wanted to reach out.")

    body = f"""Hi [FIRST NAME],

{hook}

I'm {SENDER} - my co-founder and I build explainable demand forecasting and
scheduling for paratransit and NEMT. Not a black-box optimizer: every
scheduling decision and every denial comes with the specific reason behind
it, which also makes your ADA and NTD reporting defensible when an auditor
or a rider asks.

We're choosing a small number of agencies to work with closely as design
partners. Could I show you what we found in your public numbers on a
15-minute call - and, if it's useful, run a free analysis on your own trip
data to find exactly where the deadhead is hiding?

{SENDER}
{SIGNOFF_CONTACT}"""
    return subject, body


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--state", help="filter to a state abbreviation")
    args = ap.parse_args()

    df = pd.read_csv(HERE.parent / "ntd" / "agency_economics.csv",
                     dtype={"ntd_id": str})
    df = df[df.report_year == 2024].copy()
    if args.state:
        df = df[df.state == args.state.upper()]
    # rank by the dollar hook where available, else by trips
    df["rank_val"] = df.value_10pct_deadhead_cut.fillna(0)
    df = df.sort_values(["rank_val", "trips"], ascending=False).head(args.top)

    index_rows = []
    for r in df.itertuples():
        subject, body = email_for(r)
        fname = f"{r.state}_{slug(r.agency)}.txt"
        (DRAFTS / fname).write_text(f"{subject}\n\n{body}\n", encoding="utf-8")
        index_rows.append({"file": fname, "agency": r.agency,
                           "city": r.city, "state": r.state,
                           "subject": subject})

    idx = pd.DataFrame(index_rows)
    idx.to_csv(DRAFTS / "_index.csv", index=False)
    print(f"wrote {len(idx)} personalized drafts to {DRAFTS}/")
    print(f"index: {DRAFTS / '_index.csv'}")
    print("\nEach still needs: [FIRST NAME] (find the ops/mobility manager on "
          "LinkedIn) and the sender contact line filled in.")
