"""Generate personalized design-partner outreach emails from NTD economics.

The moat-building motion: you don't buy a data moat, you earn it by getting
an operator to hand you their trip data. That starts with a cold email that
leads with THEIR numbers, not with "I'm a student." The personalized figure is
the pattern-interrupt that gets the 15-minute call; the design-partner /
free-analysis offer (see design_partner_pitch.md) is made on that call.

NO DOLLAR SAVING APPEARS IN THIS COPY. It used to: the subject led with the
agency's reported deadhead percentage and the body priced a hypothetical 10
percent cut as a hedged estimate. Both are gone (packet
MX-CLAIMS-DOLLAR-SWEEP-013). The hedge was not the problem; the premise was.
Deadhead share does not identify an expensive agency - Pearson +0.017, OLS R2
0.0003 on n=405 (research/h5b_structure_vs_cost.json); Spearman +0.024 over
406 operators against +0.738 for cost per HOUR, cost per trip flat at $48.53
in the lowest deadhead quartile against $54.09 in the highest
(business/outreach/panel_findings.json, `dr_deadhead_predicts_cost_per_trip`, REJECTED
by the panel gate). Hedging a number that does not mean what the sentence
implies just makes it harder to notice.

The hook is now the agency's national POSITION on cost per trip and the two
quantities underneath it, and there is exactly one definition of it -
`build_contact_worksheet.email_hook` - imported here so the worksheet preview
and the sent draft can never drift apart.

Two modes:

  (default) Reads business/ntd/agency_economics.csv and emits one draft per top agency
  with [FIRST NAME] left as a placeholder. Output: business/outreach/drafts/<slug>.txt

  (--merge) Reads business/outreach/contact_research_worksheet.csv (the version you
  filled with contact_name / contact_email) and emits fully-personalized,
  ready-to-send drafts - real first name, a To: line, and a one-click Gmail
  compose link - for every row that has an email. Rows still missing an email
  are skipped and reported.

Usage:
  py -3 business/outreach/generate_design_partner_emails.py            # top 40, placeholder name
  py -3 business/outreach/generate_design_partner_emails.py --top 109
  py -3 business/outreach/generate_design_partner_emails.py --state PA
  py -3 business/outreach/generate_design_partner_emails.py --merge    # from filled worksheet
"""

import argparse
import re
from pathlib import Path
from urllib.parse import quote

import pandas as pd

# One definition of the hook, shared with the worksheet. Both scripts live in
# this directory and are run as `py -3 business/outreach/<script>.py`, so the plain
# import resolves.
from build_contact_worksheet import MAX_TRIPS, MIN_TRIPS, email_hook, pctile

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


def subject_line(short_name: str, cost_per_trip: float) -> str:
    # The agency's own filed cost per trip. A hard fact, no valuation in it,
    # and a director cannot dispute their own filing.
    return f"{short_name}'s ${float(cost_per_trip):,.0f} cost per trip"


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
run a free analysis on your own trip data and show you which hours and which
runs your empty time actually sits in, at no cost and no obligation. What we
won't do is tell you what that's worth - nobody can price that from outside
your own fixed-versus-variable split. Could I borrow 15 minutes to walk you
through what we found in your public numbers?

Thanks for reading this far,
{SENDER}
{SENDER_EMAIL}"""


def email_for(r, panel) -> tuple[str, str]:
    """Placeholder-name draft from an economics row."""
    agency = short_agency(r.agency)
    if pd.notna(r.cost_per_vrh) and pd.notna(r.trips_per_vrh):
        subject = subject_line(agency, r.cost_per_trip)
        hook = email_hook(r, panel)
    else:
        # Reduced reporters file no hours detail, so the two numbers underneath
        # cost per trip do not exist for them. State the position and stop.
        subject = f"A question about {agency}'s paratransit costs"
        hook = (f"Your agency's 2024 NTD filing reports {r.trips:,.0f} "
                f"demand-response trips at ${r.cost_per_trip:,.2f} per trip, "
                f"which is percentile "
                f"{pctile(panel.cost_per_trip, r.cost_per_trip):.0f} of the "
                f"{len(panel):,} US operators filing demand-response service "
                f"that year. We pulled every US agency's numbers and wanted to "
                f"understand yours rather than guess at them.")
    return subject, body_for("[FIRST NAME]", hook)


def run_placeholder(top: int, state: str | None) -> None:
    econ = pd.read_csv(HERE.parent / "ntd" / "agency_economics.csv",
                       dtype={"ntd_id": str})
    # National panel taken before any state filter, so a percentile is national.
    panel = econ[econ.report_year == 2024].copy()
    # The mid-size band from design_partner_pitch.md, applied here too. Ranking
    # the whole panel on cost per trip alone puts 20-trip tribal programs at the
    # top -- arithmetically the most expensive operators in the country and
    # completely wrong targets. The previous ranking (deadhead dollars) hid this
    # by accident, because it scaled with size.
    df = panel[(panel.trips >= MIN_TRIPS) & (panel.trips <= MAX_TRIPS)]
    if state:
        df = df[df.state == state.upper()]
    df = df.sort_values(["cost_per_trip", "trips"], ascending=False).head(top)

    index_rows = []
    for r in df.itertuples():
        subject, body = email_for(r, panel)
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
        subject = subject_line(r.short_name, float(r.cost_per_trip))
        # The worksheet's own hook column, verbatim: one definition, so the
        # preview a human reviewed is byte-identical to what gets sent.
        hook = str(r.email_hook)
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
