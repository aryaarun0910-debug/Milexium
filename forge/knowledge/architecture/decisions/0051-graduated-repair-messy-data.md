# ADR-0051: Graduated repair — surviving messy operator exports without guessing

- **Status:** Accepted
- **Date:** 2026-07-25
- **Packet:** MX-B-MESSY-DATA-006

## Context

Paratransit and NEMT operators export whatever their vendor emits — Ecolane,
TripSpark, RouteMatch, Trapeze. The first design partner will send something
ugly. ADR-0038's adapter failed closed on everything: quarantine, never guess.
Correct for PII and genuine ambiguity, but **quarantine-everything is useless** —
rejecting 40% of an export and replying "your data is malformed" ends the
engagement, and the operator concludes we cannot handle reality.

Empirical grounding, from this repo's own work: the deadhead teardown (ADR-0039)
found **32.6% of NYC TLC rows publish no on-scene timestamp**, and that the
missingness is **correlated** — operators omitting the base id also omit the
timestamp. That is a well-maintained *public* feed. An operator's internal export
is worse.

## Decision

A **graduated response, never a silent guess**, extending the existing
`SemanticLossRecord.disposition` machinery rather than inventing a parallel one.

- **Unambiguously repairable** → repair, and record a `coerced` record naming the
  original value and the rule applied. Ten rules: `trim_whitespace`,
  `integral_float_identifier` (the `412.0` spreadsheet round-trip artifact),
  `enum_synonym`, `iso8601_variant`, `iso8601_utc_designator`,
  `twelve_hour_clock`, `date_order_ddmm`, `date_order_mmdd`,
  `requested_at_date_only`, `boolean_like`.
- **Genuinely ambiguous** → quarantine, exactly as before.
- **PII** → fails closed **first**, before any repair logic runs.

**The line, and why it is drawn there.** `date_order_ddmm`/`date_order_mmdd` fire
**only when one component exceeds 12**, which forces a single valid reading —
that is arithmetic, not a guess. When both components are ≤ 12, `03/04/2026` is
3 April *and* 4 March and nothing in the row decides it, so it is **quarantined
with a reason naming both readings**.

That refusal is the whole credibility position. Picking a reading silently would
shift a trip by a month, and every hour-of-day and day-of-week bucket in the
teardown would be wrong **while looking perfectly well-formed**. A quarantine an
operator can fix beats a number nobody can audit.

**An ingest quality report** (`themis/connect/ingest_report.py`) turns rejection
into diagnosis: rows total/mapped/repaired/quarantined, top quarantine reasons
with counts, which repair rules fired and how often, which required fields were
most often missing — and a **missingness diagnosis** using a φ coefficient to
report whether gaps are *correlated* rather than independent. Independent gaps
shrink a sample; correlated gaps **bias** it, because the rows that vanish are
systematically different from the rows that remain. A report that only counted
nulls per column would have shown two ordinary-looking gaps and hidden the bias
entirely — which is precisely what ADR-0039 hit on real data.

## Consequences

- **24 tests**, all fixtures SYNTHETIC and labelled. The 107 pre-existing
  `test_operator_export.py` tests and the 21 API tests pass unchanged.
- **PII beats repair, proven** by a row that is both malformed *and* carries a
  rider name: rejected on PII grounds, with the value surviving nowhere in the
  quarantine record.
- Trips crossing midnight and zero-duration trips are **accepted** — they are
  real, not defects. Rejecting them would quarantine the night shift.
- The degenerate cases behave: an entirely empty export produces a usable report
  rather than a `ZeroDivisionError`, and an export where *every* row quarantines
  still names its reasons and missing fields — when nothing maps, the report is
  the only thing of value we can return.

**Deliberately refused, and recorded as refusals:**

- Any ambiguous DD/MM vs MM/DD date.
- Any repair running before the PII gate.
- Inferring a missing vehicle or run reference — the teardown reports
  unattributable time as a first-class output (ADR-0039); inventing an id would
  corrupt that rather than improve it.

## Process note

The implementing agent was **stopped mid-packet**. Its `ingest_report.py` and
`operator_export.py` changes were complete and non-breaking on disk, but the test
file and packet record were missing, so the orchestrator finished both.

Worth recording: the orchestrator's first two test assumptions were **wrong** —
that `IngestQualityReport.headline` was a method, and that a space-separated ISO
timestamp required repair (it parses natively; the `iso8601_variant` rule is for
*slash-separated year-first* dates). Both were corrected against observed
behaviour rather than the tests being bent to fit. Tests written from an assumed
API rather than the real one are how a suite ends up asserting fiction.
