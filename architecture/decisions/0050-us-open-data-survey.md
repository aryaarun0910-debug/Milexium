# ADR-0050: What US open transit data is actually worth having

- **Status:** Accepted
- **Date:** 2026-07-25
- **Packet:** MX-C-US-OPENDATA-006

## Context

The question raised was whether more US open data could improve the demand
models "like a multi-billion-parameter MoE gets improved." That analogy needed
testing rather than assuming, and the prior evidence in this repo cut against it:
`realdata/transfer_control.py` kept **both** the negative and positive
transfer-learning results, and the forecast leaderboard records the NTD temporal
split **losing to seasonal naive** (R² 0.885 vs 0.972). More data does not fix a
mis-specified split.

## Decision

Survey what exists, filter it by three hard gates — **rights-clean**, **no paid
key**, **actually useful to the demand models or the canonical entities** — and
acquire only what passes, through the existing manifest-gated estate pipeline
(ADR-0013/0036).

Every figure was **measured** at acquisition (HTTP `Content-Length`, row counts
on the downloaded object, or the source's own machine-readable metadata), not
quoted from memory. Unverifiable numbers are marked **unverified** in the survey.

## Consequences

**The headline finding is a gap, not a total.** Roughly **low hundreds of GB to
~1 TB** of US open transit data exists. The volume that is rights-clean *and*
high-value for demand forecasting is **~250 MB**. Most multi-gigabyte sources are
already held, legally encumbered, or volume without forecasting value.

Measured scale (`data/US_OPEN_DATA_SURVEY.md`):

| | |
|---|---|
| Mobility Database feeds worldwide | 3,362 (2,390 static, 972 realtime) |
| US GTFS **static** feeds | 1,166 catalogued; 825 active; **816 active and keyless** |
| US GTFS **Realtime** feeds | 445 catalogued; 413 active; **246 active and keyless** |
| Distinct US transit providers with a feed | **768**, across 53 states/territories |
| NTD agencies with a monthly ridership series | **834** (Apr 2002 – Sep 2025, 293 months, 19 modes) |
| National Transit Map | **680,275 stops** / **67,588 routes** |

**Acquired: 286 MB across 12 catalogued datasets** (6 new this packet), each with
declared rights. The genuinely valuable ones, and why:

- **`ntd-monthly-ridership-all-modes` (70.8 MB)** — 834 agencies × 293 months.
  This is the one that matters, because it buys **breadth across operators**,
  which is what transfer learning needs, rather than more rows for agencies
  already held.
- **`ntd-service-opex-by-mode-timeseries` (73.2 MB)** — the cost side of the same
  panel.
- **`ntm-stops-national` (109.4 MB) / `ntm-routes-national` (9.7 MB)** — federal
  network structure.
- **`mobility-database-catalog` (1.1 MB)** — small but strategically the most
  useful: it is the index that makes acquiring the 246 keyless US GTFS-Realtime
  feeds tractable, feeding the observation entities (ADR-0035).

All US federal sources are recorded as public domain; each non-federal source
carries its actual licence (Apache-2.0, ODbL 1.0, and the MassDOT agreement whose
commercial clause remains **machine-unverifiable** and is flagged as such).

**31 conformance tests** assert every new manifest loads, declares real rights
rather than a placeholder, and that each acquired object's catalog checksum
matches the file on disk.

## The honest conclusion on scaling

**This is not the MoE regime.** LLM scaling works because more diverse text
improves general language modelling. Demand forecasting is tabular, small-N per
series, and dominated by local structure — this agency, this route, this hour.
Bulk-acquiring the remaining hundreds of GB would very likely produce **no
measurable model improvement** while consuming disk, time and the free-space
guard.

What plausibly helps is **more distinct operators** (breadth for transfer), which
is why the monthly-ridership panel was prioritised over more rows for agencies
already held, and **GTFS-Realtime feeds**, which are under-exploited and now
tractable via the catalogue.

And the binding constraint is unchanged: **286 MB or 1 TB, it is all still
public data, and public data leaves the project Demonstrated.** Only consented
operator data crosses to Validated.

**Not acquired, deliberately:** anything requiring registration or a paid API
key; the full NYC TLC archive (already partly held, and the rest is volume
without new signal); and the ~90 NTAD datasets, whose count is BTS's own claim
and was not independently verified.
