# ADR-0079: One decision episode, end to end

- **Status:** Accepted
- **Date:** 2026-07-26
- **Packet:** MX-ONT-DECISION-EPISODE-016
- **Closes:** ADR-0072's own stated limitation — *"not wired into the solver,
  forecaster, evidence packs or API"*

## Context

ADR-0072 built the ontology and recorded honestly that it connected to nothing.
147 tests, excellent scaffolding, no traffic. The unit it exists to hold is a
**decision episode**, and none existed.

## Decision

`DecisionSnapshot` → decision → `ActionRecord` → `ActionOutcome`, on **SQLite and
PostgreSQL 17 with RLS in force** — ran, not skipped.

From one snapshot, `themis/ontology/episode.py` writes: an `ASSIGNMENT` object per
placement (which by construction did not exist at `as_of`), the serving and
performing edges, one `ASSIGN` `ActionRecord` per placement carrying alternatives,
verifier verdict, policy version and authority, the solver's optimality claim as
DERIVED facts, a `TRIP_DENIED` event per denial carrying its binding constraints,
and a foreclosure edge per consumed pooling opportunity.

`reconstruct_episode(store, action_id)` recovers the vignette in a fresh process
against a closed-and-reopened database: *request arrived 10:02, vehicle expected
free 10:41, two pooling opportunities consumed at weights 0.62/0.31, one denial
for `NO_ACCESSIBLE_CAPACITY`, pickup 14 minutes late.*

### The seam holds without an import edge

**Neither side gains an import.** `themis/ontology` imports nothing from `metis`;
what crosses is plain data plus two **structural** adapters that read a producer
by attribute name and raise `DecisionSeamError` naming the missing one. The
shared vocabulary already lived in `themis/canonical`, beneath both. Asserted by
AST in **both** directions, and the adapter is exercised against a **real**
`metis.decide.ir.DecisionSolution`, not a stub.

`episode.py` contains **zero write SQL** (AST-asserted); every write goes through
a typed store method, and the reader is free functions rather than
`OntologyStore` methods, so `test_the_store_exposes_no_generic_writer` keeps its
meaning.

### The third state, and what it changes

ADR-0072 asked for a way to distinguish *"nothing was considered"* from *"we do
not know"*. `AlternativesProvenance` = ENUMERATED / NONE_CONSIDERED /
**NOT_RECORDED**, persisted with a CHECK and resolved by one shared function so
column and field cannot drift.

**An empty tuple now falls to NOT_RECORDED.** That changes the reading of every
pre-existing empty tuple in the repo from *"nothing considered"* to *"unknown"* —
which is the honest reading, and is the point.

`decision_result_from_solution` has **no parameter** through which
NONE_CONSIDERED could be claimed (pinned by `inspect.signature`), because a
`DecisionSolution` cannot support that claim.

## Consequences

**41 new tests**, ontology suite **188 passed**. Full suite 2964 passed at the
time of the run, with concurrent packets in flight.

**13 mutations, 13 RED first time, 0 GREEN** — run twice, with and without `-x`,
so the catching test could be *identified* rather than assumed. Two fixtures were
built specifically two-decision and two-action to avoid the recurring vacuity
shape where the fixture never reaches the guarded case.

**The leakage probe carries two positive controls, because the assertion alone is
vacuous.** Sentinel facts written after the decision are absent from the
reconstructed information set, its record, its provenance manifest and its
feature vector — *and* `fact_history` must show the poison landed (else the write
never happened), *and* a later snapshot over the same scope must admit it (else
scope, not the boundary, is what was measured). Deleting an admitted fact with the
trigger dropped makes reconstruction raise: it **re-derives, it does not cache.**

## Honest limitations

- **`ActionKind` has no "deny".** A denial is an event, not a permissioned
  action — so it has no authority check, no verifier verdict, no alternatives.
  A real gap in ADR-0072's vocabulary needing a twelfth kind, a permission and a
  CHECK.
- **ADR-0073's decision-time `capacity_value` is read but not wired; ADR-0065's
  retrospective `exposure` is.** `CapacityValue` reports a mean count with a
  standard error and does not name *which* future trips, so it cannot produce
  per-opportunity edges without reaching into internals this packet may not
  touch. **Consequence: the episode carries retrospective attribution, not the
  decision-time estimate.**
- **The weight is a participation share, not a probability** — the fraction of
  minimal blocking sets a commitment appears in. A reader who takes it for a
  probability will be wrong.
- `record_decision_episode` **cannot verify the decision used only the
  snapshot** — it did not make the decision. It makes the claim falsifiable,
  which is the strongest thing available from this side of the seam.
- Episode keyed on snapshot id (assumes one snapshot per solver run); no
  `episode_id`, no supersession, concurrency untested.

## Four questions this forces us to ask the first operator

1. **Can their scheduler say whether it enumerates rejections for a *whole
   batch*?** If logging depends on the code path — exact solver logs candidates,
   greedy fallback does not — every fallback decision records as a *forced*
   placement when it is actually unknown. That is the exact error the field exists
   to prevent, one level up. Cheap before backfill, impossible after.
2. **Is the denial reason captured in the same transaction as the denial?** If
   keyed in later its receipt time is later, and a replay scores the dispatcher as
   having denied a trip for no stated reason.
3. **Can they name, for 20–30 real denials, which earlier trip consumed the
   capacity?** The attribution is only as good as our feasibility model;
   unmodelled constraints (driver break, depot bay, securement type) make the
   blocking sets **confidently wrong** with nothing in the record to show it.
   This is the validation that decides whether these edges may ever be shown to an
   operator.
4. **Does any system record which version of the service rules was in force on a
   date?** If `policy_version` is invented at ingest, every *"did the policy change
   cause this?"* question is unanswerable.
