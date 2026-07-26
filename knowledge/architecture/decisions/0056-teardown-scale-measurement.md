# ADR-0056: Measuring the teardown, and what the measurement moved

- **Status:** Accepted
- **Date:** 2026-07-25
- **Packet:** MX-H-SCALE-BENCHMARK-008
- **Relates to:** ADR-0026 (polyglot triggers), ADR-0039 (deadhead teardown), ADR-0042 (HTTP/SDK surface)

## Context

ADR-0026 named three triggers for adding a second language, and one of them is
**a measured bottleneck**. Until now nobody had measured. The teardown was the
obvious candidate — it is the heaviest analytical path we own, and ADR-0039
anchored it on 66,940 segments, which is a month, not a year.

The question is asked often enough that leaving it to intuition guarantees it
gets re-asked. So: measure it, and record the answer where the next person
finds it.

## Decision

**The trigger has not fired. Python stays. No second crate is justified.**

`app/replay/teardown.py` is byte-identical after this packet — it was
measured, not modified.

### What the ladder shows

Seven rungs of real NYC TLC FHVHV rows, nested so each is a superset of the
last, on a working ultrabook under genuine memory pressure (i7-10510U, 16 GB,
2.6 GB free at start) — deliberately the slow end, so a pass is conservative.

| segments | rows | wall (s) | µs/seg | peak RSS |
|---:|---:|---:|---:|---:|
| 40,000 | 26,000 | 2.80 | 69.9 | 141 MB |
| 66,940 *(ADR-0039 anchor)* | 42,837 | 4.14 | 61.8 | 191 MB |
| 200,000 | 123,253 | 13.66 | 68.3 | 450 MB |
| 500,000 | 305,907 | 46.09 | 92.2 | 1,017 MB |
| 1,000,000 | 605,190 | 76.46 | 76.5 | 1,923 MB |
| 2,000,000 | 1,200,000 | 107.61 | 53.8 | 3,756 MB |
| 5,000,000 | 2,990,817 | 156.54 | 31.3 | 5,954 MB |

Every rung completed. It stopped at 5M because that was the largest rung
requested — roughly 10× a realistic operator year — not because anything broke.

The load-bearing statement is not the total, it is the **per-segment cost: 31 to
92 µs with no upward trend.** The largest rungs are cheaper per segment than the
smallest. Memory is linear to within a ~1% band (519 B/segment transient, ~1.1
KB/segment all-in). A mid-size operator's year is ~300k–600k segments, which
lands at ~46–55 s and under a gigabyte.

## Consequences

### The finding that is not null

A null result on ADR-0026 is not the only thing this produced. **46 s is a fine
batch job and an unacceptable interactive one.**

The teardown is reachable from the ADR-0042 HTTP/SDK surface. At operator scale
that is a 46-second synchronous request — already broken today, at current
volumes, with no growth required. The benchmark was aimed at a language question
and found a latency defect on a different surface.

**The fix is caching or async, not a language.** Recorded here as a known limit
rather than left implicit in a results file.

### Why a rewrite would have optimised the wrong thing

**~50% of the runtime is `segment_set_fingerprint`** — two ISO strings per
segment, a full sort, canonical JSON, SHA-256. That is ADR-0039 *audit* cost,
not analysis. Then ~26% hour-boundary splitting, ~7–11% run grouping, ~7% bucket
rollup, ~7% headline totals. Shares are stable at every rung.

So the single largest cost is optional bookkeeping. A port would have carried it
across and made it faster, when the cheaper question is whether it must run at
all on every call — and that question is answerable in Python, first.

### Honest limitations

- **Wall-clock swings ~2.8× with thermal state.** The same 40k rung read 25
  µs/seg cold and 70 µs/seg throttled. The ladder therefore proves the *absence
  of superlinear blow-up*; it cannot resolve n from n log n, and does not claim
  to.
- Rungs above 200k were **timed once**.
- Rungs are a contiguous slice of **one month**. This supports runtime-vs-size
  claims only. **ADR-0039's 8.89% is neither restated nor revised.**
- **FHVHV is rideshare, not paratransit.** It is the right shape for a scale
  test and the wrong population for a behavioural claim.
- The 5M rung drove the machine into sustained paging (~21 min). That is this
  laptop's ceiling, not the code's.

### On the test that gates this in CI

`test_stage_attribution_covers_the_call_it_claims_to_explain` originally
asserted stage coverage `> 50.0`. It read 40.7 while an unrelated PostgreSQL
suite ran concurrently, and passed on the same commit run alone. Coverage is a
ratio between two independently-timed passes, so it measures the machine as much
as the code.

The floor was removed and a **150% ceiling** kept: contention cannot inflate
stage totals past wall time, but double-counting timers can, so the bound that
survives is the one that still catches a defect. A 100% bound would have been
wrong — one rung legitimately reads 115%. The coverage question itself is
answered in `teardown_scale.md`, where the number can be re-read and re-run
instead of silently gating CI.

**Deliverables:** `evidence/benchmarks/performance/teardown_scale.py`,
`teardown_scale_results.json`, `teardown_scale.md`,
`evidence/conformance/property-tests/test_teardown_scale.py` (17 tests; 6 skip cleanly
without the corpus so CI stays green without it).
