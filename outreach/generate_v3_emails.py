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

# HARD BLOCK. These targets produce a striking-looking number that we do not
# yet trust, so no draft is generated for them at all -- a note in a file is
# not a safeguard, an empty drafts folder is.
#
# Montebello: ranks 3rd of 185 at 44.3% empty vehicle-hours, but reports 9.54
# trips per vehicle-hour against a 2.13 peer median (4.5x). That combination
# points to a reporting-model difference rather than an idle fleet. Leading
# with "3rd worst in the country" to a director who knows his own books, on a
# filing artifact, is unrecoverable. Verify the filing by hand to release.
HOLD_FOR_VERIFICATION = {
    "Montebello Bus Lines": "trips/VRH 9.54 vs 2.13 peer median - suspected reporting-model difference",
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
    who = first_name or "there"
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

    lines += [
        "",
        "I can show you which hours and which runs.",
        "",
        "Want it?",
        "",
        SENDER,
    ]
    return "\n".join(lines)


def main() -> None:
    insights = json.loads(INSIGHTS.read_text(encoding="utf-8"))
    written, manual, skipped, held = 0, [], [], []

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
        first = (ins.get("contact_name") or "").split()[0] if ins.get("contact_name") else ""
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
    if manual:
        print(
            f"\nNEEDS A HUMAN-RESEARCHED HOOK ({len(manual)}) -- no honest peer finding, "
            f"do NOT auto-generate:\n  " + ", ".join(sorted(manual))
        )


if __name__ == "__main__":
    main()
