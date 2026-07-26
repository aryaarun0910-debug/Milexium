# ADR-0068: A demo whose best moments are refusals

- **Status:** Accepted
- **Date:** 2026-07-26
- **Packet:** MX-DEMO-EVIDENCE-WALKTHROUGH-010

## Context

Two audiences, one artifact. A 40-year paratransit authority has invited us to
evaluate live agency deployments and wants to meet. And the platform is ~2,300
tests and 67 ADRs — **rigour that is completely invisible to anyone who does not
read code.**

## Decision

`py -3 -m argus.demo` — one command, **2.5 seconds**, the real chain end to end:

messy operator-style export → PII gate → graduated repair and quarantine →
canonical records → a scheduling decision with its reasons → deadhead teardown →
serve-time drift → an evidence pack that **re-verifies itself**.

### The refusals are the demo

A demo that only shows successes misrepresents this product, because the load-
bearing behaviour is declining to overclaim. **Six refusals are surfaced
explicitly**, each with the reason it is a feature:

1. **PII quarantined ahead of everything else**, values redacted — the first send
   imports **0 of 4 rows**.
2. An **ambiguous date declined** while its unambiguous twin is repaired.
3. The operator's own denial **left without a reason rather than back-filled**.
4. **No savings envelope** without the operator's own cost split.
5. Empty time that cannot be attributed **left unattributed** (43.0 min).
6. A conformal interval **withdrawing its own coverage guarantee** under measured
   drift (`unsupported` on 9 drifted features).

The pack re-verifies across **76 checks with 0 mismatches**, so the closing move
is not "trust us" — it is the artifact checking itself in front of the viewer.

The run ends: **"Demonstrated. Not Validated. No customers, no pilots, no
operator data."**

## Consequences

**28 tests** actually run the demo and assert on its output, so a change that
breaks it fails CI rather than rotting silently. Full repo suite **2337 passed,
1 skipped**.

It is also the platform's **first honest end-to-end integration test** — every
other suite exercises one program.

## Honest limitations

- **The data is synthetic and the output says so on the line it appears**
  (`24.4%, SYNTHETIC data`). Nothing here is evidence about any real agency.
- The teardown figure comes from a small synthetic export, so **24.4% is a
  property of the fixture**, not a finding.
- The demo shows the chain that exists today. The Cal-ITP scheduled-deadhead work
  (ADR-0062) and the intervention evaluation (ADR-0064) are **not** in it.
- Runtime is measured on one machine; ADR-0056 recorded a 2.8× thermal swing and
  ADR-0061 saw 4.2× between two runs, so 2.5 s is indicative.
