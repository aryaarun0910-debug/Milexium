"""Generate personalized design-partner outreach emails from NTD economics.

The moat-building motion: you don't buy a data moat, you earn it by getting
an operator to hand you their trip data. That starts with a cold email that
leads with THEIR numbers, not with "I'm a student." The personalized figure is
the pattern-interrupt that gets the 15-minute call; the design-partner /
free-analysis offer (see design_partner_pitch.md) is made on that call.

Honesty about the deadhead dollar figure: NTD reports deadhead as a share of
vehicle-HOURS. build_economics.py attributes operating expense to hours
uniformly, so the "value of a 10% deadhead cut" is a MODELLED estimate, not
guaranteed cash - fixed costs (salaries, depreciation, admin) don't fall
proportionally. So the copy leads the SUBJECT with the agency's real reported
deadhead percentage (a hard filing fact) and treats the dollar number in the
body as an explicit, rounded estimate whose real value is what the free
analysis is for. That keeps the first sentence unchallengeable by a director
who knows their own books.

Two modes:

  (default) Reads ntd/agency_economics.csv and emits one draft per top agency
  with [FIRST NAME] left as a placeholder. Output: outreach/drafts/<slug>.txt

  (--merge) Reads outreach/contact_research_worksheet.csv (the version you
  filled with contact_name / contact_email) and emits fully-personalized,
  ready-to-send drafts - real first name, a To: line, and a one-click Gmail
  compose link - for every row that has an email. Rows still missing an email
  are skipped and reported.

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


def subject_line(short_name: str, dh_frac: float) -> str:
    # The deadhead % is the agency's own reported figure (deadhead hours /
    # total hours) - a hard fact, not the modelled dollar estimate. Safe to
    # put in the subject; a director can't dispute their own filing.
    return f"{short_name}'s {dh_frac:.0%} paratransit deadhead"


def hook_paragraph(trips, cpt, dh_frac, dollars) -> str:
    # Trips and cost-per-trip are hard filing facts. The dollar figure is an
    # explicit estimate: rounded, hedged, and framed as the thing the free
    # analysis exists to pin down - not a savings promise.
    dh = f"{dh_frac:.0%}"
    approx = f"${round(float(dollars), -4):,.0f}"
    return (f"Your agency's 2024 NTD filing reports {float(trips):,.0f} "
            f"demand-response trips at ${float(cpt):,.2f} per trip, and about "
            f"{dh} of your vehicle-hours run empty (deadhead). Attributing cost "
            f"to hours, trimming that by even 10 percent points to something "
            f"like {approx} a year, though how much is really recoverable "
            f"depends on your fixed-versus-variable costs, which is exactly what "
            f"we'd want to pin down with you.")


def body_for(first_name: str, hook: str) -> str:
    """The warm, human body. Leads with the agency's own numbers (the hook),
    then owns the out-of-the-blue nature and the student angle. Deliberately
    frames the tool as assisting dispatchers (not autonomously denying riders),
    and promises an auditable trail rather than 'defensible' compliance."""
    return f"""Hi {first_name},

{hook}

I'll be honest, this is a bit out of the blue. I'm {SENDER}, and my co-founder
and I are engineering students who got a little obsessed with one problem:
paratransit and NEMT scheduling loses a lot of money and driver hours to empty
miles, and almost none of the software shows planners why it schedules the way
it does.

So we built something that does. It forecasts demand and helps your dispatchers
build the schedule, and every suggestion it makes, including when a trip can't
be fit in, comes with the reason behind it. The upshot for you is an auditable
trail: when an auditor or a rider asks why a decision was made, the answer is
already on record.

I'm not here to sell you anything today, we're students trying to learn from
people who actually run this before we build the wrong thing. In return we'll
run a free analysis on your own trip data and show you where the deadhead is
really hiding, at no cost and no obligation. Could I borrow 15 minutes to walk
you through what we found in your public numbers?

Thanks for reading this far,
{SENDER}
{SENDER_EMAIL}"""


def email_for(r) -> tuple[str, str]:
    """Placeholder-name draft from an economics row."""
    agency = short_agency(r.agency)
    if pd.notna(r.deadhead_pct_hours) and pd.notna(r.value_10pct_deadhead_cut) \
            and r.value_10pct_deadhead_cut > 0:
        subject = subject_line(agency, r.deadhead_pct_hours)
        hook = hook_paragraph(r.trips, r.cost_per_trip, r.deadhead_pct_hours,
                              r.value_10pct_deadhead_cut)
    else:
        subject = f"A question about {agency}'s paratransit costs"
        hook = (f"Your agency's 2024 NTD filing reports {r.trips:,.0f} "
                f"demand-response trips at ${r.cost_per_trip:,.2f} per trip. We "
                f"pulled every US agency's numbers and yours stood out enough "
                f"that we wanted to reach out.")
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
        subject = subject_line(r.short_name, float(r.deadhead_pct))
        hook = hook_paragraph(r.annual_dr_trips, r.cost_per_trip,
                              float(r.deadhead_pct), r.deadhead_dollars_per_yr)
        body = body_for(first, hook)
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
