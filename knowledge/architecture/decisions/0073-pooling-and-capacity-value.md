# ADR-0073: Foreclosure at decision time — and the equipment violations in our own optima

- **Status:** Accepted
- **Date:** 2026-07-26
- **Packet:** MX-F-POOLING-CAPACITY-VALUE-013

## Context

Research established that the sector's productivity collapse is **lost
ride-sharing**, not longer trips: occupancy fell 10.0% (1.213 → 1.092 passenger
miles per vehicle mile) 2015→2024 while trips got *shorter*. **Occupancy is not a
fact about riders — it is what a scheduling system decides.**

ADR-0065 measured the cost of commingling *after* a denial. This makes the same
quantity available *before* the commitment.

## Decision

Three additive modules. `feasibility.py`, `darp_solver.py`, `cpsat_darp.py`,
`online.py`, `commingled.py`, `exposure.py` and `ir.py` are untouched.

**`compatibility.py`** — requests are nodes, an edge means two trips can feasibly
share, a hyperedge that *k* can. **The model/optimizer separation is structural,
not conventional**: a scorer receives a `ProposalView` whose exact field set is
pinned by test — no schedule, no violation list, no certificate — and returns a
float. A share exists only as a `Certificate` whose `__post_init__` demands a
module-private witness token held by exactly two functions, minted only after
**both** independent checkers return nothing on a concrete schedule. The graph
re-runs both checkers on admission, so a forged certificate is *rejected*, not
merely discouraged.

**`capacity_value.py`** — `reach(state)` counts sampled future requests admitting
a *certified* insertion; `foreclosed(a→b) = reach(a) − reach(b)`, stratified by
accessibility. Scenario trips are spliced into a rebuilt instance so the same two
checkers judge them: **the feasibility half is exact; only the demand half is a
guess.**

## Consequences

9 runs (a3-18, a4-16, a4-24 × 3 arrival seeds):

| | baseline | capacity-aware |
|---|---|---|
| Trips served | 145 / 174 | **149** |
| **Wheelchair cohort** | 31 / 60 | **35** |
| Ambulatory cohort | 114 / 114 | 114 / 114 |
| Accessible capacity preserved | 1.178 | **1.756 (+49%)** |
| Occupancy | 0.6834 | 0.6757 (**−1.1%**) |
| Feasibility violations | **0** | **0** |

**All four gained trips went to wheelchair riders, and ambulatory service was
114/114 under both — nobody paid for it.** Per-run deltas were +1, +1, +2, else
0; never negative. That is the distributional result the packet existed to test,
and it is the opposite of rationing.

It genuinely changes assignments: 7 of 9 runs differed (30 requests moved
vehicle, 34 changed pooling partner, 0 lost); 2 were byte-identical and are
reported as such.

**The cost is occupancy and it is not hidden:** −1.1% mean, swinging both ways per
run. **The capacity term is not an occupancy lever**, and the module says so.

### The finding about our own ADR-0060 result

The offline solvers win every headline — all trips served, best occupancy
(CP-SAT 0.7974 / 0.7105 / 0.8788), lowest vehicle-miles per trip — and produce
**11–16 equipment violations each**, with **0 routing violations**.

Under an equipment model, **the distance-optimal routing is infeasible in 14
places on a3-18, and its occupancy is partly achieved by pooling a real
accessible fleet could not perform.** A wheelchair rider needs a *position*, and a
deployed station consumes floor space measured in seat-equivalents; the classical
DARP capacity constraint models neither.

ADR-0060's claim stands exactly as written — CP-SAT reproduces the *published*
optima at 0.00% gap to our own bound. What this shows is that **the published
benchmark itself does not model accessibility equipment**, so a distance-optimal
DARP solution is not necessarily a servable paratransit plan. On a3-18 both
offline plans leave **0.0** accessible capacity behind, against 2.2–2.6 for the
capacity-aware online plan.

Shareability is also scarcer than intuition suggests: only **17 of 153** candidate
pairs on a3-18 are certifiably poolable, and 1–2 riders per instance can pool with
nobody at all.

### The mutation that matters most

**26 applied, 22 RED first time, 4 survived.** One is alarming:

> **A one-line policy declining every wheelchair rider passed the entire suite.**

The unserved branch hard-codes `options=0`, so the test was reading the harness's
own claim back to itself. A discriminatory planner would have shipped green.
Closed by logging `route_after` and **replaying** the run, re-asking the authority
on every vehicle at each decline.

The other three: a deleted floor-footprint check (the position count refused the
same groups in every fixture — closed with an instance where identical windows
force three riders aboard at once, so floor 4>3 refuses where load 3≤3 and
positions 1≤1 both pass); an irrevocability check unreachable via the public API;
and one where **the mutation itself was wrong** (equivalent code), replaced with a
real behaviour change.

A test of the packet's own also failed correctly in development: *"pooling never
costs more vehicle miles than serving separately"* is **false** once a genuine
shared ride is required.

**121 new tests**, 0 skipped. Full blast radius re-run: **339** across 8 suites
plus **63** in `test_darp_cpsat`, all unmodified.

## Honest limitations

- **Accessibility labels are ASSIGNED, not observed** (ADR-0065). Every
  stratified figure demonstrates that the *method* discriminates; **none is
  evidence about any real disabled rider.** Stated in three module docstrings, on
  `AccessibilityProfile.provenance`, in every `to_record()`, and in both artifacts.
- **The demand prior is a placeholder, not a forecast** — it resamples observed
  requests. Absolute foreclosure counts inherit that entirely; only the *ordering*
  of placements is defensible. Program E is deliberately not wired in.
- `reach` is **marginal, not simultaneous** — an upper bound on what a draw could
  carry.
- Order-2 is exhaustive; **order 3+ is not**, and nothing above order 3 exists.
- The planner has **no improvement phase**, so it is weaker than the offline
  solvers by construction (14/16 vs 16/16 on a2-16). That gap is the cost of
  irrevocable commitment.
- **Weights were not tuned** (1.0 / 2.0, no sweep). Capacity-aware planning is
  10–25× slower.
- Occupancy and VMT/trip are **not stratified** — that needs an allocation rule.
- Benchmark covers **3 of 24** instances; the other 21 are named.
- Status: **Demonstrated** at most.
