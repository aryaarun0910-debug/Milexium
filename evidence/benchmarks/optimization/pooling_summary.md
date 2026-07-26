# Pooling and future capacity value -- benchmark summary

Generated 2026-07-26T09:44:12.095180+00:00 by `evidence/benchmarks/optimization/pooling_benchmark.py`.

> **Status: Demonstrated at most.** The Cordeau instances are synthetic academic
> benchmarks and support ALGORITHMIC claims only. **The accessibility labels are
> ASSIGNED by the harness, not observed** -- the published instance files carry no
> accessibility attribute whatsoever (ADR-0065). No stratified figure below is
> evidence about any real disabled rider's access to service.

> **Framing:** this measures capacity being RELEASED, never rationed. The planner
> structurally cannot decline a rider it could serve. Read `trips_served` before
> `occupancy`: an occupancy gain paid for with somebody's trip is a defect.

## Decision-level results

Occupancy is passenger miles per vehicle mile -- the quantity that fell 10.0%
sector-wide 2015->2024 while trips got *shorter*.

| instance | policy | info | trips | wheelchair | ambulatory | occupancy | veh-mi/trip | acc. capacity preserved | violations |
|---|---|---|---|---|---|---|---|---|---|
| a3-18 | cheapest-insertion (seed 1) | online | 16/18 | 4/6 | 12/12 | 0.6702 | 21.53 | 1.2 | 0 |
| a3-18 | capacity-aware(w=1.0) (seed 1) | online | 16/18 | 4/6 | 12/12 | 0.6287 | 22.05 | 2.6 | 0 |
| a3-18 | cheapest-insertion (seed 2) | online | 17/18 | 5/6 | 12/12 | 0.6248 | 20.33 | 1.0 | 0 |
| a3-18 | capacity-aware(w=1.0) (seed 2) | online | 17/18 | 5/6 | 12/12 | 0.6855 | 19.37 | 2.2 | 0 |
| a3-18 | cheapest-insertion (seed 3) | online | 17/18 | 5/6 | 12/12 | 0.6585 | 19.46 | 1.4 | 0 |
| a3-18 | capacity-aware(w=1.0) (seed 3) | online | 17/18 | 5/6 | 12/12 | 0.6150 | 19.34 | 2.2 | 0 |
| a3-18 | lns (seed 1) | offline* | 18/18 | 6/6 | 12/12 | 0.7686 | 17.56 | 0.0 | 11 |
| a3-18 | cpsat-darp (seed 1) | offline* | 18/18 | 6/6 | 12/12 | 0.7974 | 16.69 | 0.0 | 16 |
| a4-16 | cheapest-insertion (seed 1) | online | 13/16 | 3/6 | 10/10 | 0.6616 | 19.11 | 2.2 | 0 |
| a4-16 | capacity-aware(w=1.0) (seed 1) | online | 13/16 | 3/6 | 10/10 | 0.5816 | 19.72 | 2.2 | 0 |
| a4-16 | cheapest-insertion (seed 2) | online | 13/16 | 3/6 | 10/10 | 0.5158 | 20.48 | 1.8 | 0 |
| a4-16 | capacity-aware(w=1.0) (seed 2) | online | 14/16 | 4/6 | 10/10 | 0.5488 | 20.59 | 1.8 | 0 |
| a4-16 | cheapest-insertion (seed 3) | online | 13/16 | 3/6 | 10/10 | 0.7169 | 19.00 | 1.6 | 0 |
| a4-16 | capacity-aware(w=1.0) (seed 3) | online | 13/16 | 3/6 | 10/10 | 0.7169 | 19.00 | 1.6 | 0 |
| a4-16 | lns (seed 1) | offline* | 16/16 | 6/6 | 10/10 | 0.7086 | 17.71 | 2.8 | 16 |
| a4-16 | cpsat-darp (seed 1) | offline* | 16/16 | 6/6 | 10/10 | 0.7105 | 17.67 | 3.8 | 14 |
| a4-24 | cheapest-insertion (seed 1) | online | 19/24 | 3/8 | 16/16 | 0.7722 | 19.48 | 0.2 | 0 |
| a4-24 | capacity-aware(w=1.0) (seed 1) | online | 20/24 | 4/8 | 16/16 | 0.8234 | 18.63 | 0.8 | 0 |
| a4-24 | cheapest-insertion (seed 2) | online | 18/24 | 2/8 | 16/16 | 0.8092 | 17.97 | 1.0 | 0 |
| a4-24 | capacity-aware(w=1.0) (seed 2) | online | 18/24 | 2/8 | 16/16 | 0.8092 | 17.97 | 1.0 | 0 |
| a4-24 | cheapest-insertion (seed 3) | online | 19/24 | 3/8 | 16/16 | 0.7212 | 19.05 | 0.2 | 0 |
| a4-24 | capacity-aware(w=1.0) (seed 3) | online | 21/24 | 5/8 | 16/16 | 0.6724 | 19.24 | 1.4 | 0 |
| a4-24 | lns (seed 1) | offline* | 24/24 | 8/8 | 16/16 | 0.8202 | 16.51 | 1.0 | 13 |
| a4-24 | cpsat-darp (seed 1) | offline* | 24/24 | 8/8 | 16/16 | 0.8788 | 16.23 | 1.4 | 14 |

\* The offline rows see **every request before committing to any**. They are a
distance yardstick, not a like-for-like opponent for the online policies, and both
are accessibility-blind -- their violation counts say what the current planner does
under an equipment model, not that they are broken in their own terms.

## Did the decision actually change?

| instance | seed | identical | moved | gained | lost | pooling changed | trips | wheelchair trips | occupancy |
|---|---|---|---|---|---|---|---|---|---|
| a3-18 | 1 | False | 3 | 0 | 0 | 4 | +0 | +0 | -0.0416 |
| a3-18 | 2 | False | 9 | 0 | 0 | 9 | +0 | +0 | +0.0606 |
| a3-18 | 3 | False | 1 | 0 | 0 | 2 | +0 | +0 | -0.0435 |
| a4-16 | 1 | False | 3 | 0 | 0 | 2 | +0 | +0 | -0.0801 |
| a4-16 | 2 | False | 1 | 1 | 0 | 1 | +1 | +1 | +0.0331 |
| a4-16 | 3 | True | 0 | 0 | 0 | 0 | +0 | +0 | +0.0000 |
| a4-24 | 1 | False | 5 | 1 | 0 | 6 | +1 | +1 | +0.0511 |
| a4-24 | 2 | True | 0 | 0 | 0 | 0 | +0 | +0 | +0.0000 |
| a4-24 | 3 | False | 8 | 2 | 0 | 10 | +2 | +2 | -0.0488 |

## Compatibility graph

| instance | nodes | edges | hyperedges | proposals | certified | rejected by routing | rejected by equipment | isolated | equipment can bind |
|---|---|---|---|---|---|---|---|---|---|
| a3-18 | 18 | 17 | 8 | 167 | 25 | 142 | 2 | 2 | True |
| a4-16 | 16 | 23 | 12 | 177 | 35 | 141 | 6 | 1 | True |
| a4-24 | 24 | 31 | 13 | 322 | 44 | 278 | 2 | 1 | True |

`isolated` counts requests with no certified sharing partner at all -- riders whose
trip cannot be pooled however good the planner is. An occupancy target that ignores
them is a target that will be met by declining them.

## Coverage

Covered: a3-18, a4-16, a4-24.

**NOT covered** (21 of the published set): a2-16, a2-20, a2-24, a3-24, a3-30, a3-36, a4-32, a4-40, a4-48, a5-40, a5-50, a5-60, a6-48, a6-60, a6-72, a7-56, a7-70, a7-84, a8-64, a8-80, a8-96. Named rather than silently dropped.

