# ADR-0058: A findings gate that rejects more than it publishes

- **Status:** Accepted
- **Date:** 2026-07-25
- **Packet:** MX-OUTREACH-PANEL-FINDINGS-009

## Context

`build_peer_insight.py` computes one agency's national rank. Our first
substantive inbound — a former WMATA accessibility chief — asked a different
question: *"Has your work revealed any definitive conclusions or items that the
industry has so far overlooked?"* That needs sector-level findings, and
sector-level findings are exactly where a plausible-looking artifact is most
dangerous, because nobody in the room can check them live.

## Decision

A findings engine whose **gate is the product**. Every candidate must pass
mode-provenance, composition (balanced panel), and concentration (per-agency
median alongside any aggregate); money-over-years must additionally pass an
inflation check, and DR-specific claims a control-mode check. **A finding that
never *ran* a required check is rejected for that alone** — silence is not a pass.

**9 findings survived. 8 were rejected.** The rejected list is committed, with
reasons, because it is the evidence the gate works.

### The orchestrator's own correction was wrong, and the packet proved it

This is the part worth recording. The orchestrator instructed the packet to
encode "`forge/business/ntd/agency_economics.csv` is ALL MODES COMBINED" as a guard. **It is
not.** Measured rather than assumed: its `vrh` matches the mode-tagged DR-only
total for **100.0%** of 2024 agencies and the all-mode total for only **50.1%** —
precisely the share running a single mode. `actual_hours − deadhead_hours == vrh`
within 1% for 86.5% of deadhead filers (median ratio 1.000), carrying that scope
onto the deadhead columns. OmniRide: 40,140 − 27,778 = 12,362, exactly its
DR-only VRH.

The orchestrator's supporting argument was also a reasoning error: that a
deadhead tail of 9-in-406 collapsing to 1-in-45 under a DR-dominant filter proved
mode contamination. **Both are 2.22% — the identical rate.** Only ~11% of filers
are DR-dominant, so one survivor is what subgroup size predicts. There is now a
test, `test_the_extreme_tail_is_NOT_blamed_on_mode_mix`, that fails if anyone
reinstates that explanation without the rates actually differing.

The mode-provenance check was built anyway — it is a good gate — and re-derives
that agreement statistic on every run, so a future data refresh that *did* switch
to an all-mode denominator would auto-reject every deadhead finding.

**The tail remains rejected**, on honest grounds: effect size (2.2% of operators,
1.37% above a 10,000-hour floor) and concentration (two of the nine run 232 and
36 vehicle-hours *a year*; one is Montebello, already hard-blocked).

### The rejection that costs us something

**Deadhead does not predict cost per trip.** Spearman **+0.024** across 406
operators; cost *per hour* ranks +0.738. **This undercuts the hook our own v3
peer engine leads with.** It is in the committed rejected list rather than quietly
dropped, and it is unresolved.

## Consequences

**76 tests, 21/21 mutations caught** — every gate check individually neutered,
both outreach holds removed, the competitor block emptied, and a temporary hold
rewritten as a permanent opt-out. Two mutations initially escaped and both
exposed real weakness: the hold test matched a **substring**, so renaming a key
to `UNHELD <firm>` passed while the hold was disabled (now an exact key match
resolved from the CSV, with a mirror property); and the volatility-myth test
asserted only "rejected", which a failing control check delivered anyway.

`generate_expert_emails.py` **refuses to emit any draft containing a number it
cannot trace to a named field of the findings JSON**, and blocks
rationing/compliance-ceiling framing by regex — both constraints derived from the
recipient's published positions. Both guards fired on the agent's own first draft
and **the copy was fixed, not the guards.**

### Outreach holds applied

PSTA and County Connection → `HOLD_FOR_VERIFICATION`, live drafts deleted,
worksheet status updated, `do_not_contact` untouched (verified: 1 before, 1 after,
3 cells changed in the whole file). RTA parked with a HOLD naming Anne Arundel,
**not resolved either way** — it needs the founder.

**Two the orchestrator missed:** Christian Kent *himself* was a live segment-A
target with a verified direct address, and **Foursquare ITP**, his named teaming
partner. Both hard-blocked. We were one generator run from cold-emailing a man
mid-correspondence.

## Honest limitations

- **Nothing here is causal.** Every finding describes a filed number moving.
- **A bug in the packet's own code moved the headline** — the month-completeness
  filter counted *rows*, and an agency running DR under two types of service
  files two rows per month, silently excluding every multi-contract operator.
  Fixed to distinct months, with a test as its headstone. **This is the class of
  error most likely still hiding elsewhere.**
- **13.5% of deadhead filings are internally inconsistent**
  (`actual − deadhead ≠ vrh`). Recorded, not corrected.
- **Deadhead is 2024-only.** No time series exists; the by-mode file has no
  total-hours column. Not approximated.
- **CPI-U is the one constant not under repo data governance** — declared with
  its BLS series id and flagged external in the artifact.
- **Artifact regression tests only bite at regeneration time** — mutating the
  builder alone does not fail them until `panel_findings.json` is rebuilt. Same
  property `peer_insights.json` has.
- **The 5% effect floor is a knife-edge**: fleet utilisation is −3.9% aggregate
  but −5.5% on per-agency medians and would survive on that basis. The
  conservative side was taken; the threshold is arbitrary and stated.
- **There is no `DT` mode in this vintage** — taxi/TNC are `Mode=DR` with
  `TOS=TX/TN`. A test fails if a real DT code appears.
- **The panel is filers, not the industry.** Passenger miles are a Full Reporter
  obligation (22.6% coverage), which is why the pooling finding died.
- **Angle selection is keyword-matched** on `what_they_do`. Crude — a human must
  check which angle went to whom.
- **The strongest surviving findings are still efficiency-flavoured**, and the
  recipient's published thesis is that efficiency work on the legacy trip
  population is polish on a 1990s artifact. The copy avoids rationing and
  compliance-floor framing, but **no generator can resolve that tension** — his
  reply needs a human.
