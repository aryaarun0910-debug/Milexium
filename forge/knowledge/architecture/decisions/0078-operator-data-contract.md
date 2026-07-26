# ADR-0078: What we ask an operator for, and what we refuse

- **Status:** Accepted
- **Date:** 2026-07-26
- **Packet:** MX-TALOS-OPERATOR-CONTRACT-016

## Context

Milexium has **zero operator data**, and that is the only thing standing between
Demonstrated and Validated. A former WMATA accessibility chief has invited us to
evaluate live agency deployments; what converts that invitation into data is a
precise, honest answer to *"what exactly do you need from us?"*

**This is a contract, not a connector.** Its value is that it states what we must
ask for and what each field buys, so an agency's IT lead can answer *yes / no /
we don't record that* per line.

## Decision

### Three requirement levels, not two

Marking the source-side knowledge timestamp `required` makes the contract
**unanswerable** — many systems have none, and an operator whose honest answer is
"we don't record that" would send nothing at all. Marking it `helpful`
understates it. So `required_for_replay` says exactly what happens: the claim is
**withdrawn, not approximated.**

### The required set adds nothing new

**9 columns, identical to ADR-0038's published list.** A test asserts the set
equals `themis.connect.operator_export.REQUIRED_COLUMNS` plus the
vehicle-or-run pair, in **both directions**, so the document and the adapter
cannot promise different things.

Each earns its place: `requested_at` because demand is when people *ask* (without
it a three-week-ahead booking and a same-morning one are one event);
`scheduled_pickup_at` because lateness is undefined without a promise to be late
against; `vehicle_ref` **or** `run_ref` because deadhead is measurable only by
chaining one vehicle's consecutive trips (ADR-0039); `outcome` because it
separates "happened late" from "did not happen", and without it every rate has an
unknown denominator.

Plus **6 declarations** — answers, not data, one email: `export_generated_at`,
`coverage_window` (tells a quiet Sunday from a missing day),
`timestamp_convention` (without it every on-time number is wrong *while looking
well-formed*), `fleet_shape` (ADR-0057 — decides whether `vehicle_ref` is a
person id), `source_systems`, `alternatives_logged` (empty vs unknown).

### The validator is the artifact that matters

A presence check is nearly worthless here, because **the field that matters most
is the one most likely to be present and meaningless.** Four degeneracy checks,
all pure arithmetic, each with a fixture that *would pass* a presence check:

- `KNOWN_AT_CONSTANT`
- `BACKFILL_SIGNATURE` — events span weeks, knowledge spans hours
- `KNOWN_AT_EQUALS_EXPORT_TIME`
- `KNOWN_AT_PRECEDES_EVENT`

On an export without knowledge timestamps it reports: *supports outcome analysis,
deadhead measurement and unmet-demand forecasting; **cannot** support
information-set replay.* It names the 10:30-knew / 11:00-exported case, states
the **direction** of the bias — **in our favour** — and says the export is still
worth sending and that this cannot be retrofitted.

Arrivals-replay and state-replay are separate verdicts, because a created
timestamp rebuilds which bookings existed, not the board.

## Consequences

**65 tests, 0 skipped.** Both the JSON Schema and the human-readable companion
are **generated** from one Python source of truth by the existing `generate.py`,
so the CI drift gate covers them with no workflow change.

**33 mutations, 29 RED first time. Four came back GREEN and all four were real
test gaps:**

- Negative-answer matching: **both** unreadable-answer fixtures happened to
  contain no negative token, so the rule that stops *"I have no idea"* reading as
  *"no"* was certified by tests that never exercised it. Same shape as every
  other vacuous test found this month.
- A hardcoded "six" and a computed six are the same string today; the test
  asserted the value, not the derivation.
- One mutation was right and the branch was **dead** — deleted rather than
  covered.
- The false-positive direction: an operator sending `run_ref` alone would have
  been told a required column was missing.

**Minimum viable ask: 8–12 weeks, one agency, complete over the window, not
filtered.** An export of served trips only is treated as a defect in the extract,
not a perfect service record. A 200-row sample first, through the validator.

## What we deliberately do not request

Rider identifiers **even hashed** (the tokenisation is unsalted), driver ids,
fare and payment, GPS breadcrumbs, live API access. **Free text is refused, not
merely unrequested.**

**The omission that costs something real, stated rather than buried:** there is
no per-trip accessible-vehicle-required flag, so unmet *accessible* demand cannot
be measured directly — only the subset the operator already coded. Given the
introduction came from an accessibility chief, that is raised as a decision for
his counsel rather than resolved silently in either direction.

## Honest limitations

- **No operator has seen this.** Every field is a request; the requirement levels
  are our judgement, and the field list derives from what this repo can consume,
  not from any real vendor export.
- The validator reports on the **sample**, not the eventual export.
- The identity gate is a backstop — a name in a column called `ref2` passes.
- The ADR-0057 classifier gap stays open, and vehicle-identity vocabulary now
  exists in **two local copies** which should converge.
- Degeneracy thresholds are stated rules about data nobody has seen.
