# ADR-0067: Forecasting the decision, not the number

- **Status:** Accepted
- **Date:** 2026-07-26
- **Packet:** MX-E-CAPACITY-FORECAST-010

## Context

The forecast predicted demand. A planner commits **vehicle-revenue-hours**. The
distance between *"we predict 4,200 trips"* and *"you need 61 vehicle-hours to
serve 95% of them within policy"* is the distance between a model and a product.

And the two errors are not symmetric: **under-provisioning denies a
legally-entitled ADA trip; over-provisioning wastes money.** A squared-error
objective prices them identically, which makes it the *wrong* objective rather
than merely a rough one.

## Decision

1. **Forecast the committed quantity** — vehicle-revenue-hours at a stated
   service level.
2. **The cost asymmetry must be stated, never defaulted.** No field in the cost
   structure has a default. A hidden default here silently decides policy on an
   operator's behalf, and the operator would never see the decision being made.
3. **The interval guarantee propagates into the recommendation.**
   `CapacityRecommendation.interval_guarantee` is a **required** field, copied
   from the underlying forecast, so a recommendation built on an ADR-0049
   `unsupported` interval carries that status structurally. Coverage is claimable
   only when the guarantee is `unqualified` **and** the calibration sample
   supports the level; otherwise the claim is withdrawn while the vehicle-hours
   figure is **still returned** — reporting a number without a guarantee is
   useful, silently keeping the guarantee is not.

## Consequences

**74 tests** (51 + 23). Full repo suite **2337 passed, 1 skipped**.

Backtest: 640 agency-service series, a 30-month forward validation window never
touched by the 36-month conformal calibration window. Median measured
productivity 2.21 trips/VRH. The implied newsvendor critical ratio is a median
**0.734** (range 0.237–0.942) against the 0.5 a squared-error model targets — the
gap between those two numbers is the whole argument for the asymmetry.

### The result argues against the packet's own mechanism

The headline is `model_cost_aware` beating the squared-error-optimal plan on
**87.7% of series at +40.3% median cost reduction**. The controls decompose it,
and the decomposition is not flattering:

| comparison | wins | median reduction |
|---|---|---|
| vs `naive_cost_aware` (**is it the model?**) | 91.2% | +40.5% |
| vs `model_mean` (**is it the asymmetry?**) | 73.3% | **+7.3%** |
| `naive_cost_aware` vs `naive_mean` | 53.0% | **+2.5%** |

**The point forecast is doing most of the work.** Cost-aware inflation applied to
a naive forecast buys 2.5%; the asymmetry on top of a good forecast buys 7.3%.
The packet exists to argue for the asymmetry, and its own controls say the
asymmetry is the smaller half. That is recorded here rather than in a footnote,
because the controls were run precisely so the headline could not be quoted
without them.

**Mutation-verified independently by the orchestrator** (the agent was killed
before finishing its own mutation run, with one unresolved): forcing coverage to
be claimable regardless of guarantee status fails **11 tests**. The guarantee
propagation is genuinely non-vacuous.

## Honest limitations

- **The stated costs are an illustrative placeholder** ($75 per unserved trip,
  $60 per idle vehicle-revenue-hour), **not an operator's numbers**, and every
  figure above moves with them. This is the most misquotable thing in the packet.
- **Nothing is Validated.** Public NTD panels only; no consented operator data.
- The critical ratio is derived per series from that series' own measured
  productivity, so a series with unusual productivity gets an unusual ratio — the
  range 0.237–0.942 is wide and not all of it is meaningful.
- Monthly granularity; a real capacity decision is made daily or by run.
- **One unresolved mutation was inherited.** The original agent recorded that
  "M8 came back GREEN" and was killed before determining whether the mutation or
  the test was at fault. The orchestrator's independent mutation of the central
  invariant passed convincingly, but M8 itself was never identified and its
  finding is lost.
