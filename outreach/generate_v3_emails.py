"""Generate v3 cold emails from computed peer insights.

Copy rules are researched, not invented -- see outreach/craft_notes.md for the
sources behind every one of these:

- subject: lowercase, 2-4 words, <=33 chars (lowercase beats Title Case +21%;
  2-4 words ~46% opens; <=33 chars is the only length that renders on every
  mobile client). We use the rank itself -- "8th of 171" -- which is short,
  specific, and unmistakably not marketing.
- body: 55-75 words (150+ words = 42% fewer replies than <50; sub-80 is the
  2026 sweet spot; a cold email gets ~9 seconds of attention).
- no pitch. The observation carries the value and the reader draws the
  conclusion (Josh Braun: ditch the pitch, poke the bear).
- ONE interest-based CTA, never a meeting ask (interest CTAs ~30% success, 2x
  any other type; meeting asks trigger loss aversion; single-ask lifts replies
  35-42%).
- curiosity gap: we say we can show them WHICH hours and WHICH runs, and stop
  there. That specific is what they have to reply to get.
- plain text, ZERO links, no attachments (the structural factors that actually
  drive deliverability -- keyword-based spam scoring is largely a myth now).

Only agencies whose insight passes the honesty gate in build_peer_insight.py
get an email here. A target with no real finding is NOT given a manufactured
one; it is written out to a needs_manual_hook list for a human-researched
angle instead.

Usage:
  py -3 outreach/build_peer_insight.py && py -3 outreach/generate_v3_emails.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).parent
DRAFTS = HERE / "drafts"
DRAFTS.mkdir(exist_ok=True)
INSIGHTS = HERE / "peer_insights.json"

SENDER = "Arya"

MAX_WORDS = 80

# HARD BLOCK. No draft is generated for these targets at all, and any draft
# left on disk by an earlier run is DELETED -- a note in a file is not a
# safeguard, an empty drafts folder is.
#
# Two kinds of hold live here, and both are temporary pending a human decision.
# Neither is `do_not_contact`: that column is permanent and structural (see
# outreach/README.md), and downgrading a reversible hold into a permanent
# opt-out would silently burn a valid target forever.
#
# (a) NUMBERS WE DO NOT TRUST
# Montebello: ranks 3rd of 185 at 44.3% empty vehicle-hours, but reports 9.54
# trips per vehicle-hour against a 2.13 peer median (4.5x). That combination
# points to a reporting-model difference rather than an idle fleet. Leading
# with "3rd worst in the country" to a director who knows his own books, on a
# filing artifact, is unrecoverable. Verify the filing by hand to release.
#
# (b) RELATIONSHIP CONFLICT
# PSTA and CCCTA are both named, published clients of Christian Kent
# (ctktmc.com customer list; see outreach/research/christian_kent_brief.md
# section 5.1), the consultant whose unprompted reply to our cold outreach is
# the reason the panel-findings work exists at all. Cold-emailing two of a
# man's own clients while his warm thread is open is the kind of thing that
# reads badly in hindsight and costs us nothing to sequence properly -- and if
# it did cost us the relationship, we would never find out why. PSTA is doubly
# connected: his client AND the employer of his TCRP SB-38 panel co-member.
# Release only on an explicit human decision about sequencing.
HOLD_FOR_VERIFICATION = {
    "Montebello Bus Lines": "trips/VRH 9.54 vs 2.13 peer median - suspected reporting-model difference",
    "Pinellas Suncoast Transit": (
        "RELATIONSHIP HOLD - published client of Christian Kent, whose warm "
        "reply is open; sequencing is a human decision, NOT a do_not_contact"
    ),
    "County Connection": (
        "RELATIONSHIP HOLD - published client of Christian Kent, whose warm "
        "reply is open; sequencing is a human decision, NOT a do_not_contact"
    ),
}

# Greet these WITHOUT a first name. In each case the person's name is either
# unconfirmed or (worse) inferred, and the address is usually a departmental
# inbox -- so opening "Hi <name>," risks greeting someone who has left, which
# is the single clearest tell of a scraped list. A nameless greeting into a
# shared inbox is honest; a confidently wrong name is not.
NO_FIRST_NAME = {
    "City of Tallahassee": "Angela Baldwin last confirmed Apr-2024; address is a coordinator inbox",
    "Pinellas Suncoast Transit": "Bonnie Epstein's title rests on a 2023 org chart (now 404); Planning inbox",
    "Santa Cruz Metropolitan Transit District": "April Warnock not datable to 2025/26; ParaCruz inbox",
    "The Hop": "'Luis Pino' is INFERRED from the address itself, never confirmed on a source",
}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:50]


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def subject_for(ins: dict) -> str:
    """Short, lowercase, internal-looking. The rank IS the hook."""
    return f"{ordinal(ins['deadhead_rank'])} of {ins['n_peers']}"


def body_for(ins: dict, first_name: str, short_name: str) -> str:
    who = first_name or "there"  # nameless greeting for NO_FIRST_NAME targets
    rank = ordinal(ins["deadhead_rank"])
    n = ins["n_peers"]
    dh = ins["deadhead_pct_hours"]
    med = ins["peer_median_deadhead_pct"]

    lines = [
        f"Hi {who},",
        "",
        f"Of the {n} US operators running roughly your demand-response volume, "
        f"you have the {rank}-highest share of vehicle-hours running empty. "
        f"{dh}%, against a {med}% median.",
    ]

    # The dollar line only appears when there is a real gap to close, and it is
    # always hedged: overstating recoverable cash to someone who knows their own
    # books loses the account on line three. The hedge is what makes it credible.
    #
    # Word budget: the dollar line costs ~22 words, so when it is present the
    # attribution collapses to a short clause. Sub-80 words is the whole point
    # (150+ words = 42% fewer replies), and the rank is doing the work either way.
    val = ins.get("modelled_gap_value_usd")
    if val and val >= 100_000:
        amount = (
            f"${val/1_000_000:.1f}M"
            if val >= 1_000_000
            else f"${round(val/1000)*1000:,}"
        )
        lines += [
            "",
            "That's from your own NTD filing, benchmarked nationally.",
            "",
            f"At your cost per hour the gap is roughly {amount} a year — though how "
            "much is genuinely recoverable depends on your fixed-versus-variable split.",
        ]
    else:
        lines += [
            "",
            "That's your own NTD filing benchmarked against the national panel — "
            "not something visible from inside your own numbers.",
        ]

    # WARMTH (v3.1). The v3 close was "Want it?" -- two words, and read as a
    # stranger demanding a decision. The research this file follows says an
    # INTEREST-based CTA beats a meeting ask; it does NOT say be terse to the
    # point of coldness, and I conflated the two.
    #
    # The register evidence is in the first reply we got. A public-sector
    # assistant declined and signed off "Have a great day. Take care, Tan." That
    # is who these emails go to -- ops staff, often decades in the job, not SaaS
    # founders. A Valley-terse close reads as brusque from an unknown student.
    #
    # So: same single low-friction ask, same sub-100 words, same no-small-talk
    # opening -- but the close gives them an easy exit and thanks them for the
    # time either way. Warmth is not padding; it is not making the reader do
    # emotional work to forgive the tone.
    lines += [
        "",
        "I've mapped which hours and which runs it sits in — happy to send that "
        "over if it's useful to you.",
        "",
        "Either way, thanks for reading.",
        "",
        SENDER,
    ]
    return "\n".join(lines)


def main() -> None:
    insights = json.loads(INSIGHTS.read_text(encoding="utf-8"))
    written, manual, skipped, held, unverified = 0, [], [], [], []

    for short_name, ins in sorted(insights.items()):
        if short_name in HOLD_FOR_VERIFICATION:
            held.append(short_name)
            # remove any draft generated by an earlier run, so a held target
            # cannot be sent by accident from a stale file
            (DRAFTS / f"V3_{slug(short_name)}.txt").unlink(missing_ok=True)
            continue
        if ins.get("status") != "ok" or not ins.get("headline"):
            manual.append(short_name)
            continue
        email = (ins.get("contact_email") or "").strip()
        if not email:
            skipped.append(short_name)
            continue
        # An "unverified" address was reconstructed from a search-engine index
        # rather than seen on the page (usually because the site 403s automated
        # fetches). It is not from a data broker, but nobody has actually laid
        # eyes on the source. Sending to it risks a bounce, and bounces cost
        # sending reputation on a list we only get one pass at -- so a human
        # eyeballs the source page before it becomes a draft.
        if (ins.get("contact_confidence") or "").strip() == "unverified":
            unverified.append(short_name)
            continue
        first = (ins.get("contact_name") or "").split()[0] if ins.get("contact_name") else ""
        if short_name in NO_FIRST_NAME:
            first = ""
        subject = subject_for(ins)
        body = body_for(ins, first, short_name)

        wc = len(body.split()) - 2  # discount greeting + signature tokens
        flag = "  <-- OVER WORD BUDGET" if wc > MAX_WORDS else ""
        out = DRAFTS / f"V3_{slug(short_name)}.txt"
        out.write_text(
            f"To: {email}\nSubject: {subject}\n\n{body}\n", encoding="utf-8"
        )
        print(f"  {short_name[:38]:38} subj='{subject}' {wc:>3}w{flag}")
        written += 1

    print(f"\nwrote {written} v3 drafts to {DRAFTS.relative_to(HERE.parent)}")
    for name in held:
        print(f"\nHELD (no draft generated): {name}\n  reason: {HOLD_FOR_VERIFICATION[name]}")
    if skipped:
        print(f"\nno contact email yet ({len(skipped)}): {', '.join(sorted(skipped))}")
    if unverified:
        print(
            f"\nNEEDS A HUMAN TO EYEBALL THE SOURCE ({len(unverified)}) -- address "
            f"not seen directly, no draft written:\n  " + ", ".join(sorted(unverified))
        )
    if manual:
        print(
            f"\nNEEDS A HUMAN-RESEARCHED HOOK ({len(manual)}) -- no honest peer finding, "
            f"do NOT auto-generate:\n  " + ", ".join(sorted(manual))
        )


if __name__ == "__main__":
    main()
