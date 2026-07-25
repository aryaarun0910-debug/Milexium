# Handoff — 2026-07-25 (night)

Written at session limit. Read this before touching anything.

---

## UPDATE — second session limit, wave 6 in flight

**Committed since the first handoff:** ADRs 0057–0061 + tranche-5 docs, one commit
per packet, CI green. HEAD was `7003a41`. Suite ~1900.

**SEVEN packets were still running when this session ended.** Their work is on
disk, uncommitted, possibly half-written. **Do not `git add -A`.** Run the suite
first to see what landed, then review and commit **per packet with file-level
`git add`**. Next free ADR number: **0062**.

| Packet | Owned paths |
|---|---|
| A — lifecycle decision record | `packages/canonical/**` |
| H — intervention evaluation | `packages/replay/**` except `teardown.py` |
| F — commingled exposure | `packages/decide/**` |
| Demo — evidence walkthrough | `demo/**`, `docs/DEMO.md`, `artifacts/demo-walkthrough/` |
| I — third-party verification | `packages/evidence/**` |
| C — Cal-ITP GTFS block harvest | `packages/estate/**`, `data/catalog/**`, `tools/**` |
| E — capacity forecast | `packages/forecast/**`, `benchmarks/quality/**` |

### The Kent thread — this is the company's most valuable asset

He replied twice on 2026-07-25, warmly, and: **engages free of charge**, corrected
his own 2023 position gracefully, and **invited us to evaluate live agency
deployments** — the only route to consented operator data and therefore to
**Validated**. A reply is drafted in Gmail answering his two questions (we are
UK/Loughborough; not yet APTA, joining) and asking for the smallest possible
thing: before/after operational records for **one** agency.

**The line that defines the opportunity**, verbatim:

> *"I agree with you that there is insufficient new data to support any conclusion
> that the new software has done any better, but I am persuaded that they are on
> the right track."*

**And the line that defines the wedge**, verbatim:

> *"reduction in cost due to greater efficiency (and replacement of some human
> resources with artificial intelligence)"*

At several agencies, decisions formerly made by humans — including trip denials
and time negotiations — are **now made by an AI**. Under the ADA those are
appealable acts and the basis of pattern-or-practice findings. So the question
that lands is **not** "can we improve your algorithms" (he published against that
framing) but:

> **When the AI denies a wheelchair user's trip, can the agency show why?**

That is a liability his clients acquired this year and have probably not priced,
and the answer to it is a decision record captured at decision time — Program A's
lifecycle packet. Frame efficiency as **releasing capacity**, never rationing;
frame compliance as proving an agency **exceeded** the floor, never that it
cleared it. Both are his published positions.

### Strategy decided this session: be the referee, not the competitor

Do **not** try to reverse-engineer Trapeze/Ecolane/Via/Spare — proprietary,
closed, legally messy, losing game. Instead **publish the honest public benchmark
that does not exist**. ADR-0060 proves optimal DARP solutions at 0.00% gap to our
own rigorous bound. Nobody in this industry runs a reproducible scoreboard.
Kent writes **RFP evaluation criteria** — a referee is what his leverage needs,
and it sidesteps his 2023 objection entirely (we are not polishing the artifact,
we are measuring whether anything improved).

### YC context

F26 batch IS being announced (GodHands lists "Batch: Fall 2026"); an earlier
claim in-session that it was unannounced was wrong — it came from reading a
placeholder directory page. Of four F26 companies reviewed (Simantic, RunInfra,
Degla, GodHands), **three show no customers** and Degla's headline demo is a
*simulation*. Founder pedigree, a two-person team, and a **one-sentence
description** are doing the work in those admissions. Milexium lacks the
sentence — it has been described three different ways in one session. Candidate:
**"We prove whether transit software actually worked."**

### Deferred by the founder

Website for Chris — **next session**. Build a comparison against Chris's version,
then fuse the two. Not started, deliberately.

---

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
