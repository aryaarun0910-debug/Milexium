# ADR-0062: Measured deadhead, and the word "scheduled" that must never fall off it

- **Status:** Accepted
- **Date:** 2026-07-25
- **Packet:** MX-C-GTFS-BLOCK-HARVEST-010

## Context

Everything the platform could say about deadhead came from **annual NTD
filings** — one self-reported number per operator per year. We inferred deadhead;
we never observed it. Program A defines `Block`, `RunPiece` and `DeadheadSegment`
(ADR-0047) and those entities had no real data behind them.

GTFS `trips.txt` carries `block_id` — a day's chained vehicle work. Chaining
consecutive trips within a block yields a **derived** deadhead segment.

`data/ACQUISITION_PLAN.md` named the Cal-ITP GTFS-Ingest Pipeline Dataset as the
de-risking step: rights-clean, keyless, ~200 California operators, no national
harvest and no unresolved FTA licensing question.

## Decision

Acquire the seven Cal-ITP GTFS tables through the governed estate and derive
scheduled deadhead per block.

**Rights were verified, not inherited.** CC-BY with commercial use permitted,
confirmed by reading the publisher's own machine-readable CKAN record
(`data.ca.gov/api/3/action/package_show`) rather than trusting the acquisition
plan's own summary — that plan's figures were explicitly estimates. All seven
manifests declare commercial rights; a test asserts it.

### The word "scheduled" is the decision

A GTFS-derived figure says **what the timetable implies, not what vehicles did.**
It omits pull-out and pull-in from the depot (usually absent from GTFS
altogether), it cannot distinguish a layover from genuine non-revenue movement
without assumption, and it knows nothing about schedule deviation.

So the measurement is named `scheduled_deadhead` at every level — the emitted
segments carry `"measurement": "scheduled_deadhead"`, and the summary fields are
`scheduled_deadhead_hours`, `scheduled_layover_hours`, `scheduled_revenue_hours`.
**It must never be compared against NTD's operated figure as though they were the
same quantity.** Where the two are put side by side, the difference is a
*definitional* gap first and an operational finding second — and we do not
currently know how much is which.

Movement time and layover time are separated rather than merged, because merging
them is exactly how a scheduled figure gets quietly inflated toward the operated
one.

## Consequences

**120 tests passed, 6 skipped.** 73.5 MB of real `trips.csv` plus six companion
tables on disk under declared rights, checksum-verified through
`packages/estate/acquire.py`.

This is the first deadhead number in the repo that is **derived from primary
records rather than self-reported**, and it gives Program A's scheduling family
its first real data.

## Honest limitations

- **Scheduled, not operated.** Stated above; it is the whole point and the most
  likely thing for a future reader to forget.
- **California only.** ~200 operators, one state, not a national panel. The
  national harvest depends on an FTA licensing answer the founder has not yet
  received, and was deliberately not attempted.
- **Depot pull-out/pull-in is absent**, so this systematically *understates* true
  deadhead by an unknown amount.
- **Layover-versus-deadhead requires an assumption**; the split is reported but
  the boundary between them is a modelling choice, not an observation.
- Agencies that publish no usable `block_id` cannot be measured at all — their
  absence from the result is not evidence of low deadhead.
- Public GTFS is **not operator-consented data**. Status is **Demonstrated**;
  nothing here approaches Validated.
