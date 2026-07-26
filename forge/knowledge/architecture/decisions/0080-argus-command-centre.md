# ADR-0080: Argus — the operating picture, and the prohibition as a type

- **Status:** Accepted
- **Date:** 2026-07-26
- **Packet:** MX-ARGUS-COMMAND-CENTRE-016

## Context

The platform is ~2,700 tests and 79 ADRs. **That rigour is invisible to anyone
who does not read code.** The existing walkthrough is a terminal script —
excellent, and unshowable to a transport executive.

Argus is the operational surface, and its prohibition is the whole point:

> **Argus must never invent a fact, constraint, reason or recommendation.**
> Argus renders authority; it does not manufacture authority.

## Decision

`py -3 -m argus.command_centre` → a self-contained 61 KB page that opens from
disk with no server, no build step and no network, plus `operating_picture.json`
as the machine-checkable record behind every figure. **2.4 s.**

### The prohibition is a type, not a convention

**Nothing reaches the page except as a `Figure`, which cannot be constructed
without a `Source`** naming the layer, the call site and what was read. The
renderer prints that **under every number and every table**.

47 figures this build — 14 Themis, 13 Metis, 5 Aletheia, 5 corpus, **9 DECLARED
scenario input**, 1 the page about itself.

The sharp part: **`Figure.derived_from` attributes a composite to its *weakest*
input.** A figure mixing governed counts with a modelling assumption comes out
DECLARED and renders with a different tag. That is what stops a scenario
assumption laundering itself into a governed-looking number by being averaged
with one.

Three modules, cleanly split: `attribution.py` (the prohibition), `picture.py`
(composition — decides nothing), `render.py` (no domain knowledge).

### Seven refusals are on the page

Including one that is not a rehearsal: **Argus calls `ForecastRuntime.forecast`
on every build and renders `NoChampionError` verbatim.** No forecast is served,
and none is substituted. Also: PII quarantined (0 of 4 rows imported), an
ambiguous date declined while its twin is repaired, the conformal interval
withdrawing its own coverage guarantee **in the monitor's own words** with the
exchangeable control shown coming back clean, no savings envelope without the
operator's cost split, 43.0 unattributable minutes, and the operator's denial
keeping its missing reason.

## What wiring the layers exposed — the valuable part

This is the first surface that touches all five layers, and it found four things:

1. **`DarpInstance` cannot express per-vehicle shifts.** `DecisionProblem`
   carries shift start/end per vehicle (hence `SHIFT_END`); `darp_ir.DarpInstance`
   has one depot window for the whole fleet. **So the capacity lens certifies
   insertions the scheduler denied.** Both verdicts are shown *unreconciled* with
   the structural reason stated, and the lens is used only for cost, labelled
   counterfactual. **The fix belongs in `metis/` — reported, not made.**
2. **Canonical records still cannot drive Milexium's own geometry** — no trip end
   time in the column list or on `Outcome`, so mean duration is read from the
   unmapped `ActualDO`, outside the canonical path. Second surface to hit
   ADR-0068's wall.
3. **The projection's fleet has slack the real day did not** — every committed
   block scores zero foreclosure. Tightening `max_route_duration` changed nothing.
   Reported **on the page** as a negative result.
4. **The equipment checker refused nothing (0 of 3)** — and the page says so. The
   constraint binds inside the scheduling authority instead.

## Consequences

**35 tests** in the packet, 52 including the layer-prohibition file. Full suite
**2970 passed, 1 skipped, zero failures**. `argus/demo/` untouched — imported,
not copied.

**16 mutations. 9 RED first round, 4 survived, 1 more survived a second round, 16
RED after closure.** Every survivor had the shape this repo keeps finding:

- `ACCESSIBLE_VEHICLES = 3` made the equipment layer **incapable of refusing
  anything** while `can_bind` stayed true and every assertion stayed green.
- Tables rendering *nothing* passed a marker-absence check.
- A marginal sign flip was invisible **because every value is zero**.
- The record/row pairing guard never fired.

## Honest limitations

- **Synthetic scenario**, stated in the page's own banner: *"No operator has ever
  sent this repository an export."*
- **No forecast is served, so the demand picture is entirely backward-looking.**
  "Upcoming window" describes the decision's position in time, not a prediction.
- The DARP projection needs geometry the repo does not have — a **declared**
  regular polygon whose *scale* alone is measured from the export's durations.
- **Accessibility labels are ASSIGNED** (ADR-0065), by a stated rule that says
  nothing about the outcome.
- Counterfactual foreclosure 0.75 ± 0.48 **barely clears its own standard error.**
- Deliberately excluded: any live or multi-tenant view, and the capacity-backtest
  artifact's 640 NTD series — **they carry real agency names and belong nowhere
  near an operating picture.**
