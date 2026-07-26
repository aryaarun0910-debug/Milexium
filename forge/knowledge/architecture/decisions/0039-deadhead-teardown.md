# ADR-0039: The deadhead teardown — Program H depth, and the deliverable already promised

- **Status:** Accepted
- **Date:** 2026-07-24
- **Packet:** MX-H-DEADHEAD-TEARDOWN-003

## Context

Fifteen US operators were emailed on 2026-07-24 with a specific sentence: *"I can
show you which hours and which runs."* NTD is **annual aggregate** — it can say
an agency runs 34.8% of vehicle-hours empty, and nothing about when or where.
The promise was unbacked.

Program H (simulation/replay) was also the weakest spine program at ~15%, and it
is the one that answers *"did the decision actually improve the outcome."* So the
deliverable and the roadmap gap were the same piece of work.

## Decision

`aletheia/replay/teardown.py` — `teardown_deadhead(segments, ...)` returning a
frozen `DeadheadTeardown`. It reuses `comparison.py`'s modelled-not-causal
discipline (ADR-0019) rather than restating it, and does not modify `replay.py`
or `comparison.py`.

**Which hours.** `by_hour_of_day`, `by_day_of_week`, `by_day_of_week_and_hour`.
Segments are **split at hour boundaries** (09:50→10:20 contributes 10 min to
hour 09 and 20 to hour 10), so every grouping reconciles exactly to the headline
totals — asserted as a property, not assumed.

**Which runs.** `top_runs` ranked by empty minutes. `unattributable` is a
separate `RunContribution` held **outside** the ranking, so top-N truncation can
never bury it, and a `model_validator` makes `attributable == (run_ref is not
None)` structurally impossible to fake.

**How much — and the refusals that matter more than the number.**
`value_at_full_cost` = empty hours × the operator's own rate, labelled *the
accounting value of the time*, never a saving. Then:

- `CostBasis.avoidable_share_low/high` have **no default**. Absent them,
  `envelope_basis` reads *"the recoverable fraction of this value is unknown and
  is not guessed."* The module refuses to invent a recovery rate.
- `is_guaranteed_saving=True` **raises**. `causal_proof=True` **raises**.
- `FIXED_COST_HEDGE` reuses the outreach's own wording, so the email and the
  analysis cannot drift apart.
- `DataProvenance` is `"real_public" | "synthetic"` — there is deliberately **no
  `"operator"` value**, and a test asserts it is rejected. The label cannot be
  applied until a consented export actually exists.

**Evidence.** A `TeardownManifest` with a deterministic `teardown_id`,
order-independent `segment_sha256`, every input as `(name, value, source)`, and
numbered method steps precise enough to redo by hand.

**Privacy.** `VehicleSegment` is `extra="forbid"` (a rider field cannot be
attached); `from_row` reads only the named columns; pointing `run_ref_column` at a
rider-ish column **raises** rather than silently dropping — because dropping
would leave the caller believing they had attribution.

## Consequences

**35 tests.** Demonstrated on **real public data**: NYC TLC FHVHV records, one
real calendar week (2019-02-04 → 02-10), 40k-row seeded sample → 66,940 segments.
**74,764 empty minutes vs 766,461 revenue minutes = 8.89% of vehicle time empty.**

Two findings that justify the whole packet:

1. **The highest-*rate* hours and the highest-*volume* hours are different
   hours.** Emptiest by rate: 04:00 (10.98%), 22:00, 03:00. Worst by absolute
   empty minutes: 22:00 (5,134), 18:00, 19:00. Worst joint cells: Monday 04:00
   (15.5%), Tuesday 05:00. **An annual percentage destroys exactly this
   distinction** — which is the argument for the product, produced by the product.
2. **Correlated missingness is real and dangerous.** Re-keying the same week on
   `originating_base_num` (null for Juno/Via/Lyft) put 10,918 segments and
   213,936 revenue minutes into `unattributable` — whose empty time is **exactly
   zero**, because operators omitting the base also omit the on-scene timestamp.
   A teardown that dropped null-id rows would have silently removed real vehicle
   minutes from every denominator. This is why `unattributable` is a first-class
   output rather than a filter.

**Honest limitations, all stated in-artifact:**

- **FHVHV is rideshare, not paratransit** — real and public, but not an operator
  export and not the target domain.
- **"Run" is a TLC dispatching base, not a vehicle/block/run.** FHVHV publishes
  no vehicle, driver or block id; 28 bases is the finest real fleet unit
  available. The mechanism is demonstrated and an operator's `vehicle_id` slots
  into the same field for far sharper answers. Recorded via `run_ref_source`.
- **Deadhead is measured conservatively and understates.** Only the empty
  approach drive counts; pull-out, pull-in, inter-trip repositioning and curb
  wait are excluded. The true figure exceeds 8.89%.
- **32.6% of sampled rows publish no on-scene timestamp** — reported as
  `unmeasured_segment_count` with a reason, never imputed as zero.
- **Hour buckets are in the source's own clock** — TLC publishes naive local New
  York time which this repo treats as UTC (`tlc_trips.py`), so these are local NY
  hours wearing a UTC label. Stated in the method steps.
- **The $76.885/hr rate is a stand-in** (national median `cost_per_vrh` across
  2024 NTD demand-response filings); TLC publishes no cost per vehicle-hour. The
  dollar figures exercise the arithmetic and are not a claim about NYC economics.
- **Sample, not census** — 40k of ~4.9M rows that week; shapes are
  representative, absolute totals are not.

Status: **Demonstrated**. Consumes the intake adapter from ADR-0038; note that
ADR-0038 surfaced that `vehicle_ref`/`run_ref` has no canonical home, so the
field this analysis depends on survives in memory but **cannot yet be persisted
canonically** — a Program A follow-up.
