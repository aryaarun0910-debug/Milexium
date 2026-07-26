"""Generate the expert/consultant-segment emails from PANEL findings.

How this differs from generate_v3_emails.py
-------------------------------------------
The v3 generator leads with one agency's national rank. That works on an
operator because the rank is a fact about THEM they cannot see. It is worthless
on a consultant: ranking agencies is what they do for a living, and a rank of
an agency that is not theirs is not about them at all.

So this generator leads with structure in the national panel -- the thing that
takes the whole 368,937-row NTD monthly file plus the by-mode opex series to
see, and that nobody in this market has any reason to have computed. Every
number comes out of business/outreach/panel_findings.json, and ONLY out of the
`survived` list: a finding that failed the gate in build_panel_findings.py
cannot reach an email, because the angle that would carry it refuses to build.

Copy rules are inherited wholesale from business/outreach/craft_notes.md (sources are
recorded there, not invented here):
  - subject lowercase, 2-4 words, <=33 chars
  - body 55-80 words, no pitch, ONE interest-based CTA, never a meeting ask
  - plain text, ZERO links, no attachments
  - v3.1 tone: appreciation only where genuinely earned, easy exit, no
    manufactured flattery

Three guards this file adds that the v3 generator does not have
----------------------------------------------------------------
1. NUMERIC TRACEABILITY (`verify_numbers_traceable`). Every number-like token
   in the finished subject and body must have been registered as coming from a
   named field of panel_findings.json. A number that appears in the copy
   without a citation is a hard failure and no draft is written. This is the
   packet's "never invent a figure" rule made executable rather than promised:
   these go to people who know their own books, and one wrong figure ends the
   relationship.

2. FRAMING GUARD (`FORBIDDEN_FRAMINGS`). Two framings are own goals with this
   segment and are blocked by regex, not by good intentions:
     - efficiency as RATIONING. Christian Kent's published position rejects
       trip-by-trip restriction outright ("restricting transit use should not
       be our objective", Mass Transit, 18 Apr 2023). Efficiency here is
       always RELEASING capacity, never serving fewer trips.
     - compliance as a CEILING. He notes "there is nothing in the regulations
       that prohibits going above and beyond minimum requirements", so copy
       about staying compliant reads as small. Evidence proves an agency
       EXCEEDED the floor, not that it cleared it.

3. SEGMENT HARD BLOCKS (`HOLD_FOR_VERIFICATION`, and the B-COMPETITOR rule).
   Same mechanism as the v3 generator: no draft written, and any stale draft
   on disk deleted -- an empty drafts folder is a safeguard, a note in a file
   is not.

Usage:
  py -3 business/outreach/build_panel_findings.py && py -3 business/outreach/generate_expert_emails.py
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parents[1]
DRAFTS = HERE / "drafts"
DRAFTS.mkdir(exist_ok=True)
FINDINGS = HERE / "panel_findings.json"
TARGETS = HERE / "targets_consultancies.csv"

SENDER = "Arya"
MAX_WORDS = 80  # business/outreach/craft_notes.md: the 2026 sweet spot is under 80
MAX_SUBJECT_CHARS = 33

# ---------------------------------------------------------------------------
# HARD BLOCK. No draft, and any draft from an earlier run is deleted.
# Keyed on the `firm` column of targets_consultancies.csv.
# ---------------------------------------------------------------------------
HOLD_FOR_VERIFICATION = {
    "Christian T. Kent Transit Management Consulting LLC": (
        "ALREADY IN A WARM THREAD -- he replied to our cold outreach unprompted "
        "and his question is the reason panel_findings.json exists. Generating a "
        "cold email to him from a target list would read as us blasting a list "
        "and never reading his reply. His response is written by a human, by "
        "hand, and is not this generator's business."
    ),
    "Foursquare ITP": (
        "RELATIONSHIP HOLD -- named teaming partner of Christian T. Kent "
        "(ctktmc.com; see business/outreach/research/christian_kent_brief.md 3.2) whose "
        "warm thread is open. Same conflict as the PSTA and CCCTA holds in "
        "generate_v3_emails.py: cold-emailing a man's partners while he is "
        "being generous with his time is an own goal we would never learn we "
        "had scored. Human sequencing decision, NOT a do_not_contact."
    ),
}

# Greet WITHOUT a first name: a shared inbox, or a name nobody has confirmed.
# A nameless greeting into a shared inbox is honest; a confidently wrong name
# is the clearest possible tell of a scraped list.
NO_FIRST_NAME_INBOXES = {"shared"}

# Confidence values that mean a human has not actually laid eyes on the source.
NEEDS_HUMAN_CONFIDENCE = {"not-found", "unverified", ""}

# Segments that never get an email. B-COMPETITOR is the single biggest own goal
# in this funnel (business/outreach/startup_integrator_template.md): a cold email
# describing our architecture to a competitor is free competitive intelligence.
BLOCKED_SEGMENTS = {"B-COMPETITOR"}

# Framings that must never reach this segment. Matched against the finished
# body, case-insensitively.
FORBIDDEN_FRAMINGS = (
    (r"\bfewer trips\b|\brestrict\w*\b|\bration\w*\b|\bsuppress\w*\b"
     r"|\btrip[- ]by[- ]trip\b|\bcap demand\b|\bturn (?:down|away)\b",
     "efficiency framed as restricting or rationing trips -- rejected outright "
     "by this segment's published position; frame it as releasing capacity"),
    (r"\bstay compliant\b|\bremain compliant\b|\bmeet the minimum\b"
     r"|\bcompliance risk\b|\bavoid (?:a )?(?:lawsuit|litigation)\b",
     "compliance framed as a ceiling to clear -- reads as small to people who "
     "know nothing stops an agency going above the minimum"),
)

# A number in prose. The lookbehind stops digits that are part of a word or of
# a longer number from being scanned as separate figures -- without it "p90"
# yields a phantom "90" and "$16" yields a phantom "16", and the traceability
# check then fails on copy that is perfectly well cited.
_NUMBER_TOKEN = re.compile(r"(?<![A-Za-z0-9])\$?\d[\d,]*(?:\.\d+)?%?x?")


class CopyError(RuntimeError):
    """A draft that cannot be written honestly is not written at all."""


# ===========================================================================
# Numeric traceability
# ===========================================================================
class Cited:
    """Accumulates every number used in a draft, with where it came from.

    A number is only allowed into copy through `.n()`, which records the
    finding id and the field it was read from. `verify` then proves that no
    OTHER number leaked into the text.
    """

    def __init__(self) -> None:
        self.tokens: dict[str, str] = {}

    def n(self, value: str, finding_id: str, field: str) -> str:
        self.tokens[value] = f"panel_findings.json :: {finding_id} :: {field}"
        return value

    def year(self, value: int, finding: dict) -> str:
        """A year in the copy is a claim about the observation window.

        It gets cited like any other number -- against the finding's own
        `source` string, which names the file, the filter and the endpoints.
        Whitelisting years as "obviously fine" is how a window silently drifts
        away from the data it was computed on.
        """
        if str(value) not in finding["source"]:
            raise CopyError(
                f"year {value} is not in the source window of "
                f"{finding['id']}: {finding['source']}")
        self.tokens[str(value)] = (
            f"panel_findings.json :: {finding['id']} :: source window")
        return str(value)

    def verify(self, *texts: str) -> None:
        allowed = set(self.tokens)
        for text in texts:
            for tok in _NUMBER_TOKEN.findall(text):
                if tok in allowed:
                    continue
                # A bare token may be a substring of a cited one ("16" inside
                # "$16"); only accept it if some cited token contains it AND it
                # is not a standalone claim.
                if any(tok in a for a in allowed):
                    continue
                raise CopyError(
                    f"UNTRACEABLE NUMBER {tok!r} in copy -- every figure must be "
                    f"read from panel_findings.json through Cited.n(). Cited so "
                    f"far: {sorted(allowed)}")

    def provenance(self) -> list[str]:
        return [f"{v}  ->  {k}" for k, v in sorted(self.tokens.items(),
                                                   key=lambda kv: kv[1])]


def check_framing(body: str) -> None:
    for pattern, why in FORBIDDEN_FRAMINGS:
        m = re.search(pattern, body, re.IGNORECASE)
        if m:
            raise CopyError(f"FORBIDDEN FRAMING {m.group(0)!r}: {why}")


# ===========================================================================
# Angles -- each is built from ONE survived finding
# ===========================================================================
def _f(findings: dict, fid: str) -> dict:
    """Fetch a SURVIVED finding, or refuse.

    A rejected finding is not merely unused here; asking for one is an error,
    because the only way a rejected number reaches a prospect is if somebody
    wired it up on purpose.
    """
    for d in findings["survived"]:
        if d["id"] == fid:
            return d
    rejected = {d["id"] for d in findings["rejected"]}
    if fid in rejected:
        raise CopyError(
            f"{fid} is in the REJECTED list -- it failed the gate in "
            f"build_panel_findings.py and must not appear in an email. If the "
            f"claim is wanted, fix the finding, not the copy.")
    raise CopyError(f"{fid} is not in panel_findings.json at all")


def angle_cost_dispersion(findings: dict, c: Cited) -> tuple[str, str]:
    d = _f(findings, "dr_cost_per_trip_dispersion_2024")
    n = d["numbers"]
    ops = c.n(f"{n['n_operators']:,}", d["id"], "n_operators")
    p10 = c.n(f"${n['cost_per_trip_p10_usd']:.0f}", d["id"], "cost_per_trip_p10_usd")
    p90 = c.n(f"${n['cost_per_trip_p90_usd']:.0f}", d["id"], "cost_per_trip_p90_usd")
    prod = c.n(f"{n['variance_share_productivity_pct']:.0f}%", d["id"],
               "variance_share_productivity_pct")
    spread = c.n(f"{n['p90_over_p10']:.0f}x", d["id"], "p90_over_p10")
    y = c.year(2024, d)
    subject = f"the {spread} cost spread"
    body = (
        f"Across {ops} US demand-response operators in the {y} NTD, cost per "
        f"trip runs {p10} at the tenth percentile and {p90} at the ninetieth. "
        f"About {prod} of that spread is trips per revenue hour, not the price "
        f"of an hour."
    )
    return subject, body


def angle_not_congestion(findings: dict, c: Cited) -> tuple[str, str]:
    d = _f(findings, "dr_productivity_loss_is_not_congestion")
    n = d["numbers"]
    n_ag = c.n(f"{n['n_balanced_agencies']:,}", d["id"], "n_balanced_agencies")
    s15 = c.n(f"{n['speed_vrm_per_vrh_2015']:.1f}", d["id"], "speed_vrm_per_vrh_2015")
    s24 = c.n(f"{n['speed_vrm_per_vrh_2024']:.1f}", d["id"], "speed_vrm_per_vrh_2024")
    mpt = c.n(f"{n['vehicle_miles_per_trip_change_pct']:.0f}%", d["id"],
              "vehicle_miles_per_trip_change_pct")
    y0 = c.year(2015, d)
    subject = "not traffic"
    body = (
        f"On a balanced panel of {n_ag} US demand-response operators, average "
        f"speed has not moved since {y0} — {s15} to {s24} miles per revenue "
        f"hour. Over the same decade those vehicles covered {mpt} more miles "
        f"per trip delivered. So it is not congestion."
    )
    return subject, body


def angle_cost_split(findings: dict, c: Cited) -> tuple[str, str]:
    d = _f(findings, "dr_cost_growth_split_2015_2024")
    n = d["numbers"]
    a = c.n(f"${n['cost_per_trip_2015_usd']:.2f}", d["id"], "cost_per_trip_2015_usd")
    b = c.n(f"${n['cost_per_trip_2024_usd']:.2f}", d["id"], "cost_per_trip_2024_usd")
    nom = c.n(f"{n['cost_per_trip_change_nominal_pct']:.0f}%", d["id"],
              "cost_per_trip_change_nominal_pct")
    real = c.n(f"{n['cost_per_trip_change_real_pct']:.0f}%", d["id"],
               "cost_per_trip_change_real_pct")
    prod = c.n(f"{n['attribution_productivity_pct']:.0f}%", d["id"],
               "attribution_productivity_pct")
    y0, y1 = c.year(2015, d), c.year(2024, d)
    subject = f"{nom} nominal, {real} real"
    body = (
        f"US demand-response cost per trip went {a} to {b} between {y0} and "
        f"{y1} — {nom} nominal, {real} after CPI. Roughly {prod} of the real "
        f"rise is the drop in trips per revenue hour; the rest is the price of "
        f"an hour."
    )
    return subject, body


def angle_supply_demand_gap(findings: dict, c: Cited) -> tuple[str, str]:
    d = _f(findings, "dr_hours_recovered_further_than_trips")
    n = d["numbers"]
    k = c.n(f"{n['n_more_hours_fewer_trips']}", d["id"], "n_more_hours_fewer_trips")
    tot = c.n(f"{n['n_agencies']}", d["id"], "n_agencies")
    hrs = c.n(f"{n['median_hours_recovery_pct']:.0f}%", d["id"],
              "median_hours_recovery_pct")
    trp = c.n(f"{n['median_trips_recovery_pct']:.0f}%", d["id"],
              "median_trips_recovery_pct")
    y = c.year(2019, d)
    subject = "hours back, riders not"
    body = (
        f"Across US demand-response operators, supply came back further than "
        f"demand: the median runs {hrs} of its {y} vehicle hours on {trp} of "
        f"its {y} trips. {k} of {tot} now run more hours than {y} while "
        f"carrying fewer riders — capacity already paid for."
    )
    return subject, body


# Angle selection. Keyed off what the firm actually does, so the observation is
# about their work rather than whichever finding happened to be first.
ANGLES = (
    (r"cost|financial|budget|feasibility|economic|business plan",
     angle_cost_split),
    (r"procure|specification|rfp|solicitation|system selection|oversight",
     angle_cost_dispersion),
    (r"paratransit|demand.?respons|ada|accessib|microtransit|mobility manage",
     angle_not_congestion),
    (r"operations|scheduling|run.?cut|service (?:design|plan)|efficiency",
     angle_supply_demand_gap),
)
DEFAULT_ANGLE = angle_cost_dispersion


def pick_angle(row: dict):
    blob = " ".join((row.get("what_they_do", ""), row.get("why_channel", ""),
                     row.get("firm", ""))).lower()
    for pattern, fn in ANGLES:
        if re.search(pattern, blob):
            return fn
    return DEFAULT_ANGLE


# ===========================================================================
def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:50]


def compose(row: dict, findings: dict) -> tuple[str, str, Cited]:
    c = Cited()
    subject, observation = pick_angle(row)(findings, c)

    first = ""
    name = (row.get("contact_name") or "").strip()
    if name and row.get("is_named_person_inbox", "") not in NO_FIRST_NAME_INBOXES:
        first = name.split()[0]
    who = first or "there"

    # The close. ONE interest-based ask, an easy exit, and the rejected list
    # offered alongside the surviving one -- for this audience the findings we
    # killed are better evidence of method than the ones we kept, and offering
    # them is the least extractive thing we can put in a first email.
    n_surv = c.n(str(findings["counts"]["survived"]), "_meta", "counts.survived")
    n_rej = c.n(str(findings["counts"]["rejected"]), "_meta", "counts.rejected")

    body = (
        f"Hi {who},\n\n"
        f"{observation}\n\n"
        f"That is from an NTD panel I built — {n_surv} findings that held up "
        f"under composition and concentration checks, {n_rej} that did not. "
        f"Happy to send both.\n\n"
        f"Thanks for reading either way.\n\n"
        f"{SENDER}"
    )
    check_framing(body)
    c.verify(subject, body)
    # Word budget is a REFUSAL, not a warning. 150+ words replies 42% less
    # often than under 50, and sub-80 is the researched band
    # (business/outreach/craft_notes.md). A flagged-but-written draft is a draft that
    # gets sent anyway, which makes the research decorative.
    wc = len(body.split()) - 2  # discount greeting + signature tokens
    if wc > MAX_WORDS:
        raise CopyError(f"{wc} words > MAX_WORDS={MAX_WORDS}; cut the copy, do "
                        f"not raise the budget")
    if len(subject) > MAX_SUBJECT_CHARS:
        raise CopyError(f"subject {len(subject)} chars > {MAX_SUBJECT_CHARS}: {subject!r}")
    if subject != subject.lower():
        raise CopyError(f"subject must be lowercase: {subject!r}")
    if "http" in body or "www." in body:
        raise CopyError("body contains a link; this segment's drafts are plain "
                        "text with zero links")
    return subject, body, c


def main() -> None:
    if not FINDINGS.exists():
        raise SystemExit("run: py -3 business/outreach/build_panel_findings.py first")
    findings = json.loads(FINDINGS.read_text(encoding="utf-8"))
    rows = list(csv.DictReader(TARGETS.open(encoding="utf-8-sig")))

    written = 0
    held, competitors, opted_out, no_email, needs_human, failed = [], [], [], [], [], []

    for row in rows:
        firm = row["firm"].strip()
        out = DRAFTS / f"EXPERT_{slug(firm)}.txt"

        if firm in HOLD_FOR_VERIFICATION:
            held.append(firm)
            out.unlink(missing_ok=True)
            continue
        if row.get("segment", "").strip() in BLOCKED_SEGMENTS:
            competitors.append(firm)
            out.unlink(missing_ok=True)
            continue
        if (row.get("do_not_contact") or "").strip():
            opted_out.append(firm)
            out.unlink(missing_ok=True)
            continue
        email = (row.get("contact_email") or "").strip()
        if not email:
            no_email.append(firm)
            continue
        if (row.get("confidence") or "").strip() in NEEDS_HUMAN_CONFIDENCE:
            needs_human.append(firm)
            continue

        try:
            subject, body, cited = compose(row, findings)
        except CopyError as exc:
            failed.append((firm, str(exc)))
            out.unlink(missing_ok=True)
            continue

        wc = len(body.split()) - 2  # discount greeting + signature tokens
        provenance = "\n".join(f"#   {p}" for p in cited.provenance())
        out.write_text(
            f"To: {email}\nSubject: {subject}\n\n{body}\n\n"
            f"# ---- provenance (not sent) ----\n{provenance}\n",
            encoding="utf-8")
        print(f"  {firm[:40]:40} subj='{subject}' {wc:>3}w")
        written += 1

    print(f"\nwrote {written} expert drafts to {DRAFTS.relative_to(REPO)}")
    for f in held:
        print(f"\nHELD (no draft generated): {f}\n  reason: {HOLD_FOR_VERIFICATION[f]}")
    if competitors:
        print(f"\nCOMPETITORS -- never contacted ({len(competitors)}): "
              + ", ".join(sorted(competitors)))
    if opted_out:
        print(f"\ndo_not_contact ({len(opted_out)}): " + ", ".join(sorted(opted_out)))
    if needs_human:
        print(f"\nADDRESS NOT VERIFIED BY A HUMAN ({len(needs_human)}) -- no draft:\n  "
              + ", ".join(sorted(needs_human)))
    if no_email:
        print(f"\nno contact email yet ({len(no_email)}): " + ", ".join(sorted(no_email)))
    if failed:
        print(f"\nCOPY REFUSED ({len(failed)}):")
        for f, why in failed:
            print(f"  {f}: {why}")


if __name__ == "__main__":
    main()
