# Handoff — 2026-07-25 (night)

Written at session limit. Read this before touching anything.

## Committed, pushed, CI green

| Commit | Packet | ADR |
|---|---|---|
| `0973492` | B — run-reference chain closed, adapter → Outcome → store → teardown | 0054 |
| `3d3669e` | D — migration path + refusal to invent a tenant | 0055 |
| `a225093` | H — teardown scale benchmark; ADR-0026 trigger did NOT fire | 0056 |

**Suite was 1411 passed** at `a225093`. `IMPLEMENTATION_STATUS.md` and `docs/JOURNAL.md`
are current to that point.

## ⚠️ FIVE PACKETS WERE STILL RUNNING WHEN THE SESSION ENDED

Their work is **on disk, uncommitted, and possibly half-written**. Do not
`git add -A`. Do not assume any of it is complete or correct.

| Packet | Owned paths | State |
|---|---|---|
| F — solver portfolio | `packages/decide/**`, `benchmarks/optimization/`, `test_decide_*`, `test_darp_*` | in flight |
| M — interactive latency + TS SDK | `packages/api/**`, `packages/sdk/**`, `packages/sdk-typescript/**` | in flight |
| B — remaining adapter refs | `packages/connect/**` | in flight |
| D — ModelRegistry persistence | `packages/core/**` | in flight |
| Outreach — panel findings | `outreach/**` | in flight |

**First action next session:** run the full suite (`py -3 -m pytest -q`, ~9.5 min
when the machine is quiet) to find out what actually landed. Then review each
packet's diff **separately**, write its ADR, and commit **per packet with
file-level `git add`**.

**Do NOT `git add <directory>`.** Earlier this month a `git add packages/core/`
swept a concurrent agent's in-flight work into an unrelated commit and left HEAD
importing a symbol that did not exist at that commit. File-level ownership means
file-level staging.

Next free ADR number: **0057**.

## Business — the thing with a clock on it

**A reply to Christian T. Kent is drafted and UNSENT in Gmail.** He is our first
substantive inbound: ran accessibility at WMATA, now President & CEO of Transit
Management Consulting, styles himself "Mr. Paratransit", replied 24 minutes after
a cold email. Research brief: `outreach/research/christian_kent_brief.md`.

**Read the brief before editing that draft.** The critical finding: his published
position (*Mass Transit*, 18 Apr 2023, "Have We Outgrown Paratransit?") is that
applying better algorithms to the legacy next-day paratransit trip population is
polish on "a 1990s artifact". His email to us suggested we might "improve the
algorithms being used by the latest scheduling software products" — that was
**courtesy in our vocabulary, not his thesis**. An earlier version of the draft
enthusiastically agreed with it and had to be rewritten.

Two hard framing constraints with him:
- Efficiency = **releasing capacity**, never restricting or rationing trips. He
  explicitly rejects trip-by-trip rationing.
- Compliance = proving an agency **exceeded** the floor, not that it cleared it.

### Outreach holds — one needs a human decision

- **PSTA** and **County Connection (CCCTA)** are Kent's own published clients and
  were both at "ready to send". Instructed to be held (not `do_not_contact` —
  that column is permanent and structural; this is reversible). **Verify the hold
  actually landed** before any send.
- **Transit Management of Central Maryland (dba RTA)** — operates service *for*
  Anne Arundel County, which opted out on 2026-07-25 and is correctly
  `do_not_contact`. Contacting RTA could read as routing around that removal
  request. **Frozen pending the founder's decision. Do not resolve this
  unilaterally.**

## Data findings that must not be re-derived wrongly

**`ntd/agency_economics.csv` is DEMAND-RESPONSE ONLY.** Verified by measurement:
its `vrh` matches the mode-tagged DR-only total for **100.0%** of 2024 agencies
and the all-mode total for only **50.1%** (exactly the single-mode operators).
`actual_hours − deadhead_hours == vrh` within 1% for 86.5% of deadhead filers,
carrying that scope onto the deadhead columns. OmniRide: 40,140 − 27,778 =
12,362 = its DR-only VRH exactly.

⚠️ **An earlier version of this file said the opposite.** The orchestrator saw no
mode column and one row per agency, inferred "all modes", and "corrected" a
finding that was already right. Two compounding errors, both worth avoiding
again: **inferring scope from schema shape instead of measuring it** (one join
settles it), and **a subgroup-rate error presented as evidence** — arguing that a
tail of 9-in-406 collapsing to 1-in-45 proved mode contamination, when both are
**2.22%**, the identical rate. Only ~11% of filers are DR-dominant, so one
survivor is exactly what subgroup size predicts.

The extreme deadhead tail is still **rejected** for outreach, on the honest
grounds: effect size (2.2% of operators, 1.37% above a 10,000-hour floor) and
concentration (two of the nine run 232 and 36 vehicle-hours *a year*).

**Deadhead does NOT predict cost per trip** — Spearman **+0.024** over 406
operators (cost *per hour* ranks +0.738). **This undercuts the hook the v3 peer
engine leads with, and is unresolved.**

**Deadhead is 2024-only, with no time series** — the by-mode file has no
total-hours column. 13.5% of deadhead filings are internally inconsistent. There
is **no `DT` mode** in the current vintage; taxi/TNC are `Mode=DR` with
`TOS=TX/TN`.

### What survives (mode-tagged, balanced panel, inflation-adjusted)

1,606 agencies reporting demand-response in **both** 2015 and 2024:
- trips 153.8M → 129.9M (**−15%**)
- opex $4.49B → $6.71B (**+49%**)
- cost per trip $29.19 → $51.70 (**+77% nominal, +33.9% real**, CPI-U 237.017 → 313.689)
- productivity 2.119 → 1.896 trips/VRH

Also surviving, from the monthly panel (balanced, 259 agencies in 2005/2019/2024):
20-year productivity decline of −11.2%, per-agency median −11.1%, 64% of agencies
less productive. **Not COVID** — 2024 landed on 2019.

**A killed finding, and keep it killed:** "demand-response demand is uniquely
volatile, so you need forecasting" is **FALSE**. DR month-to-month variation is
*lower* than bus (median CV 15.0% vs 18.4%).

## Data acquisition

`data/ACQUISITION_PLAN.md`. Top target is historical GTFS-Realtime — joining
vehicle positions against `block_id` yields a **measured** deadhead segment
instead of an annual self-report. Every size in that document is an **estimate**,
not measured; the scout was forbidden from downloading.

Founder actions outstanding: email FTA (GTFS licensing position) and Cal-ITP
(California TIDES without requester-pays). Census API key is **already obtained
and verified live**; it and a NOAA CDO token are in `.env` (gitignored, untracked,
confirmed absent from all history). California TIDES was ruled out — requester-pays
bucket needs cloud billing, which violates the no-paid-cloud constraint.

## Standing rules that keep being earned

- **"All tests still pass" is a weak signal immediately after a boundary change.**
  Four tests this month passed while proving nothing.
- J/K/L stay at 0% **by evidence now, not assumption** — ADR-0056 measured the
  ADR-0026 trigger and it did not fire. Program completion is not a trigger.
- Nothing is **Validated**. That word requires consented operator data and none
  exists.

## Deferred by the founder

A website for Chris, to be planned *after* the build work. Not started.
