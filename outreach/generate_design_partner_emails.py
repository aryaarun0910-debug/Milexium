"""Generate personalized design-partner outreach emails from NTD economics.

The moat-building motion: you don't buy a data moat, you earn it by getting
an operator to hand you their trip data. That starts with a cold email that
leads with THEIR money (their own NTD-reported deadhead cost), not with "I'm
a student." The personalized number is the pattern-interrupt that gets the
15-minute call; the design-partner / free-analysis offer (see
design_partner_pitch.md) is made on that call.

Two modes:

  (default) Reads ntd/agency_economics.csv and emits one draft per top agency
  with [FIRST NAME] left as a placeholder - for when you don't have contacts
  yet. Output: outreach/drafts/<state>_<agency_slug>.txt

  (--merge) Reads outreach/contact_research_worksheet.csv (the version you
  filled with contact_name / contact_email) and emits fully-personalized,
  ready-to-send drafts - real first name in the greeting, a To: line, and the
  agency's own deadhead number - for every row that has an email. Rows still
  missing an email are skipped and reported.

Usage:
  py -3 outreach/generate_design_partner_emails.py            # top 40, placeholder name
  py -3 outreach/generate_design_partner_emails.py --top 109
  py -3 outreach/generate_design_partner_emails.py --state PA
  py -3 outreach/generate_design_partner_emails.py --merge    # from filled worksheet
"""

import argparse
import re
from pathlib import Path
from urllib.parse import quote

import pandas as pd

HERE = Path(__file__).parent
DRAFTS = HERE / "drafts"
DRAFTS.mkdir(exist_ok=True)
WORKSHEET = HERE / "contact_research_worksheet.csv"

# Personal for now - sending from a real, aged Gmail lands in inboxes far more
# reliably than a brand-new company domain with no sending reputation. No site
# link on purpose: a plain 1:1 note from a person reads warmer and dodges the
# link-heavy pattern spam filters key on.
SENDER = "Arya"
SENDER_EMAIL = "aryaarun0910@gmail.com"


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


def body_for(first_name: str, hook: str) -> str:
    """The warm, human body. Leads with the agency's own number (the hook),
    then owns the out-of-the-blue nature and the student angle rather than
    hiding it - students running a free analysis is a low-risk yes, so the
    student framing is an asset here, not a liability."""
    return f"""Hi {first_name},

{hook}

I'll be honest, this is a bit out of the blue. I'm {SENDER}, and my co-founder
and I are engineering students who got a little obsessed with one problem:
paratransit and NEMT scheduling burns a lot of money and driver hours on empty
miles, and almost none of the software explains why it makes the calls it does.

So we built something that does. It forecasts demand and builds the schedule,
and every decision, including every denial, comes with the specific reason
behind it. That part is really for you: it makes your ADA and NTD reporting
defensible when an auditor or a rider asks why.

We're not trying to sell you anything. We're looking for a few agencies to
learn from, and in return we'll run a free analysis on your own trip data and
show you exactly where the deadhead is hiding, at no cost and no obligation.
Could I borrow 15 minutes to walk you through what we already found in your
public numbers?

Thanks for reading this far,
{SENDER}
{SENDER_EMAIL}"""


def email_for(r) -> tuple[str, str]:
    """Placeholder-name draft from an economics row."""
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

    return subject, body_for("[FIRST NAME]", hook)


def run_placeholder(top: int, state: str | None) -> None:
    df = pd.read_csv(HERE.parent / "ntd" / "agency_economics.csv",
                     dtype={"ntd_id": str})
    df = df[df.report_year == 2024].copy()
    if state:
        df = df[df.state == state.upper()]
    df["rank_val"] = df.value_10pct_deadhead_cut.fillna(0)
    df = df.sort_values(["rank_val", "trips"], ascending=False).head(top)

    index_rows = []
    for r in df.itertuples():
        subject, body = email_for(r)
        fname = f"{r.state}_{slug(r.agency)}.txt"
        (DRAFTS / fname).write_text(f"{subject}\n\n{body}\n", encoding="utf-8")
        index_rows.append({"file": fname, "agency": r.agency, "city": r.city,
                           "state": r.state, "subject": subject})

    idx = pd.DataFrame(index_rows)
    idx.to_csv(DRAFTS / "_index.csv", index=False)
    print(f"wrote {len(idx)} placeholder drafts to {DRAFTS}/")
    print("Each still needs [FIRST NAME] and a recipient. Fill the worksheet "
          "and re-run with --merge to get ready-to-send drafts.")


def run_merge() -> None:
    if not WORKSHEET.exists():
        raise SystemExit(f"no worksheet at {WORKSHEET} - run "
                         f"build_contact_worksheet.py first, then fill in "
                         f"contact_name / contact_email.")
    df = pd.read_csv(WORKSHEET)

    def filled(v) -> bool:
        return pd.notna(v) and str(v).strip() != ""

    ready = df[df.contact_email.apply(filled)].copy()
    missing = len(df) - len(ready)

    index_rows = []
    for r in ready.itertuples():
        first = (str(r.contact_name).strip().split()[0]
                 if filled(r.contact_name) else "there")
        val = f"${int(r.deadhead_dollars_per_yr):,}"
        subject = f"{r.short_name}: a {val}/yr question about your paratransit deadhead"
        body = body_for(first, r.email_hook)
        # One-click: opens a Gmail compose window with to/subject/body filled.
        compose = ("https://mail.google.com/mail/?view=cm&fs=1"
                   f"&to={quote(str(r.contact_email))}"
                   f"&su={quote(subject)}&body={quote(body)}")
        fname = f"SEND_{r.state}_{slug(r.agency)}.txt"
        (DRAFTS / fname).write_text(
            f"To: {r.contact_email}\nSubject: {subject}\n\n"
            f"Open in Gmail: {compose}\n\n{body}\n",
            encoding="utf-8")
        index_rows.append({"file": fname, "to": r.contact_email,
                           "agency": r.short_name, "state": r.state,
                           "subject": subject, "gmail_compose_url": compose})

    if index_rows:
        pd.DataFrame(index_rows).to_csv(DRAFTS / "_send_index.csv", index=False)
    print(f"merged {len(index_rows)} ready-to-send drafts to {DRAFTS}/ "
          f"(SEND_*.txt)")
    if missing:
        print(f"skipped {missing} rows with no contact_email yet - research "
              f"those, refill the worksheet, and re-run --merge.")
    print("Review each SEND_*.txt, then paste into Gmail (or push via the "
          "connector in a fresh session). Send ~10-15/day, not a bulk blast.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--state", help="filter to a state abbreviation")
    ap.add_argument("--merge", action="store_true",
                    help="build ready-to-send drafts from the filled worksheet")
    args = ap.parse_args()

    if args.merge:
        run_merge()
    else:
        run_placeholder(args.top, args.state)
