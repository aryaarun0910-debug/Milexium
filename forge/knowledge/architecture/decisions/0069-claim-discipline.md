# ADR-0069: The status contract, enforced on outward-facing copy

- **Status:** Accepted
- **Date:** 2026-07-26
- **Packet:** MX-DOCS-CLAIM-SWEEP-012
- **Trigger:** external audit, `MILEXIUM_INTERNAL_AUDIT_2026-07-26.md`

## Context

ADR-0001 fixed the status vocabulary — Exists / Specified / Demonstrated /
Validated / Production — and stated that **Validated requires consented operator
data**. Milexium has none: zero customers, zero pilots.

The audit found that the vocabulary was being honoured inside `app/**` and
violated in the documents that leave the building. The YC application draft said
the model was **"validated on real ridership data"** and **"validated on 26.3
million real bookings"**, and claimed the architecture had been **validated**
across cities and modalities. `COMPETITIVE_POSITIONING.md` went further and
*instructed the team* to say "validated demand forecasting" — a violation that
propagates by design.

It also carried a **$94M opportunity** figure, derived from a hypothetical 10%
deadhead reduction — a claim this week's research had already destroyed
(deadhead vs cost per trip: Pearson **+0.017**, OLS **R² = 0.0003**, n=405).

## Decision

**Repair, do not trim.** The draft is now longer and more persuasive, because the
honest version of our position is stronger than the inflated one: the reason we
have no operator data is stated plainly and framed as something a reviewer will
find anyway, which converts a weakness into evidence of how we operate.

Specific replacements:
- "validated on real ridership data" → **demonstrated**, plus an explicit note
  that a public *aggregate* borough-hour panel demonstrates the forecasting task
  and **does not validate any operator's dispatch**.
- "every assignment and every denial comes with the exact factors" → scoped to
  decisions **our own solver** makes; where the decision was the incumbent's, the
  reason is recorded as **unknown**. That is the product working, not a gap.
- The **$94M sentence was deleted outright**, not softened, and no replacement
  dollar figure was invented.

What replaced it is sourced: cost per demand-response trip **$29.19 → $51.70** on
a balanced 1,606-agency panel (+77% nominal, **+34% real** vs CPI-U), and the
occupancy collapse (passenger miles per vehicle mile **1.213 → 1.092**, trips
getting *shorter*, 66.8% of agencies losing occupancy) — carrying its selection
bias in the same sentence.

**The killed hook is presented as an asset.** The draft now states that we tested
our own lead claim, it failed, and we deleted the figure rather than softening
it. For an investor judging whether our numbers can be trusted, that is worth
more than the number was.

### The standing rule

`COMPETITIVE_POSITIONING.md` gains a **status contract** section ahead of its
claims list, so the next person writing copy cannot reach for "validated" by
accident. Three rules:

1. Never write *validated*, *proven*, *guaranteed*, or *production model*.
2. **Never publish a savings, ROI or opportunity figure**, with the $94M failure
   recorded as the worked example.
3. Every number names its artifact, or it is deleted.

## Consequences

`forge/knowledge/docs/MODEL_CARDS.md` ("validated as the right objective" ×4 → "selected in the
objective bakeoff"), `README.md` ("the production model" → "local reference
implementation"; a **250 GB** estate claim deleted rather than replaced with a
smaller number that is also not a repo artifact), and `forge/knowledge/docs/README.md` now routes
future writers to the contract.

**`app/**` came back clean.** Every package docstring already states nothing
is Validated, and `standalone_verifier.py` hard-blocks `Validated`/`Production` as
pack statuses. The discipline held everywhere it was enforced in code and failed
everywhere it was left to prose — which is the lesson.

## Honest limitations and follow-ups

- **A generator reintroduces the fix.** `talos/tools/build_model_cards.py:41,113`
  regenerates the exact strings just corrected, so the next run undoes them.
  Being handled in MX-CLAIMS-DOLLAR-SWEEP-013.
- **Worse violations exist outside this packet's paths** and are the subject of
  that same packet: a self-serve savings calculator built for the website, and
  outreach hooks writing *"A 10 percent deadhead reduction is worth about $X a
  year to you"* to named agencies.
- **13 agencies have already been sent** a hedged version of that dollar line.
  Recorded as fact; nothing can be unsent.
- `forge/knowledge/docs/JOURNAL.md` still contains the $94M line and was **deliberately not
  edited** — the journal is an append-only dated record, and erasing it would
  destroy the evidence that the claim was made and later killed.
- "26.3 million bookings" traces to `data/curated/README.md`, not to a metrics
  artifact; defensible but under-sourced.
- "2,337 passing tests" is what a local run on a provisioned machine reports. CI
  provisions no PostGIS or MinIO, so a clean runner reports fewer.
