# Milexium project journal

Newest entries first. One entry per working session: what was added, the numbers produced, decisions made, and anything running or unfinished. This is the historical record; `docs/MASTER_ROADMAP.md` is the only active backlog.

## 2026-07-25 (night): three packets, a null result, and the first real reply

**Suite 1249 → 1411 passed.** Programs B, D and H landed as three parallel
packets on disjoint paths, committed separately: `0973492` (B, ADR-0054),
`3d3669e` (D, ADR-0055), `a225093` (H, ADR-0056).

**H was the interesting one, and it produced a null result.** ADR-0026 named a
*measured bottleneck* as one of three triggers for adding a second language, and
nobody had ever measured. Seven nested rungs of real NYC TLC rows, 40k → 5M
segments, on a working ultrabook under genuine memory pressure — deliberately
the slow end so that a pass means something. Every rung completed. The
load-bearing number isn't the total but the per-segment cost: **31–92 µs with no
upward trend**, the largest rungs cheaper per segment than the smallest. A
mid-size operator's year is ~300k–600k segments → ~46–55 s, under a gigabyte.
**Python is adequate. The trigger has not fired.** `teardown.py` is
byte-identical; it was measured, not modified.

But the run found two things the verdict doesn't cover, and they matter more
than the verdict:

1. **46 s is a fine batch job and an unacceptable interactive one.** The teardown
   is reachable from the ADR-0042 HTTP/SDK surface, where that is a 46-second
   synchronous request — broken *today*, at *current* volume, needing no growth
   at all. The benchmark was aimed at a language question and found a latency
   defect on a different surface entirely.
2. **~50% of the runtime is `segment_set_fingerprint`** — sort, canonical JSON,
   SHA-256. That's ADR-0039 audit cost, not analysis. A rewrite would have
   carried the largest cost across and made it faster, when the cheaper question
   is whether it needs to run on every call. The most expensive thing in the hot
   path turned out to be optional bookkeeping.

**A fourth test-that-proved-nothing.** H's own stage-coverage assertion
(`> 50.0`) is a ratio between two independently-timed passes, so it measures the
machine as much as the code — it read 40.7 under concurrent PostgreSQL load and
passed on the same commit run alone. A test that's green on an idle laptop and
red on a loaded runner spends the suite's credibility to tell you about the
runner. Floor removed, 150% ceiling kept: contention can't inflate stage totals
past wall time, but double-counting timers can. A 100% bound would have been
wrong — one rung legitimately reads 115%.

**D's decision is a refusal.** ADR-0048 added `tenant_id NOT NULL` and honestly
recorded that pre-tenant databases aren't upgraded by reopening them, acceptable
"only because these tables have never held operator data" — which stops being
true the moment outreach works. So: a version ledger, ordered migrations, and a
raise when a populated table has no declared tenant. It doesn't choose, because
**the tidiest-looking default is the leaking one** — the ADR-0040 platform tenant
would declare an operator's private feature values platform-owned, and
platform-owned rows are readable by every tenant. Two findings the agent hit and
fixed rather than worked around: three tests failed at first because a
post-migration read with no GUC in scope returned zero rows (*the policy
working* — the tests were wrong, not the boundary), and the refusal originally
fired after the v1 stamp was already committed.

**B closed the run-reference chain** adapter → `Outcome` → store → teardown, and
narrowed the semantic-loss record rather than deleting it. Deleting was the easy
move and would have silently dropped a genuine residual claim.

### Outreach: the first substantive reply

**Christian T. Kent** — ran accessibility at WMATA, now President & CEO of
Transit Management Consulting, signs himself "Mr. Paratransit" — replied **24
minutes** after send. Positive, and he asked the one question we only get to
answer once: *"Has your work revealed any definitive conclusions or items that
the industry has so far overlooked?"*

This is the reply the warmer v3.1 register was aimed at, and it came from the
expert segment rather than an agency. Worth noting *what* he responded to: the
email led with **why he specifically** could judge the work, stated plainly that
we have no pilot and no customers, and asked for his read rather than his
business.

So I went looking for panel-level findings honest enough to answer him, in the
NTD monthly ridership panel already acquired under ADR-0050 — 23 years, 637
demand-response agencies, 152k agency-month observations. **One candidate died,
and that's the useful part:** "demand-response demand is uniquely volatile, so
you need forecasting" is **false** — month-to-month variation in DR trips is
*lower* than bus (median CV 15.0% vs 18.4%). Had we led with it, the first
expert to check would have caught us.

Two survived:

- **DR productivity has fallen for two decades** — 2.02 trips per
  vehicle-revenue-hour in 2005 → 1.79 in 2024. The obvious objection is
  composition, so it was re-run on a **balanced panel** of the 259 agencies
  reporting in 2005, 2019 *and* 2024: −11.2%, per-agency median −11.1%, 64% of
  individual agencies less productive. Not composition, not one big operator,
  and **not COVID** — 2024 landed exactly where 2019 did, so the pandemic was a
  dip-and-recover sitting on top of a much older decline.
- **The national recovery figure is nearly useless.** Median recovery is 87% of
  2019 volume, but p10 is 61% and p90 is 152% — a 2.5× spread hidden inside a
  single number everyone repeats.

The deadhead finding was re-derived properly for the reply: **406** operators in
the 2024 NTD demand-response panel, median **15.1%** of vehicle-hours deadhead,
p90 **25.5%**, with a long tail — OmniRide 69% on 40,000 vehicle-hours, TANK 61%
on 62,000. The data is public; the peer comparison isn't computed by anyone, so
an operator at 60% has no way to learn it isn't normal.

Draft reply is in Gmail for Arya to read and send. It answers his question with
the two surviving findings, gives back the one that died, asks him the two
things only he can answer — whether vendor savings claims are a live problem,
and whether anyone would actually reach for a denial-reason record — and says
plainly that we're self-funded and will take no offence if a call like this is
normally billable for him. He's a consultant with a Calendly in his signature;
booking it cold without naming money would have been naive.

**Correction to my own reporting during the session:** I flagged CI on main as
red off a notification email for `50a8d50`. It wasn't — four successful runs had
superseded it. Main was green throughout.

## 2026-07-25 (evening): tagged, superuser closed, governance unified

Three things, in the order Arya asked for them.

**Tagged `v0.4.0-pilot-conversion`** at 1248 green — the first tag in the repo,
and the rollback anchor before any archival work. The tag message carries the
known open items rather than only the wins, so the anchor is honest about what
it anchors.

**Closed the container superuser (ADR-0052).** ADR-0046 found the PostGIS
credential holds rolsuper AND rolbypassrls, and bound the STORE by having it
SET ROLE to a NOLOGIN role — but recorded the honest limit that the credential
itself stayed all-powerful, so anything else using it still bypassed every
policy. Now there is `milexium_app`: a LOGIN role, NOSUPERUSER, NOBYPASSRLS,
with only what the store needs. Verified: the store connects as it,
`rolsuper=False`, and `_acting_role` is None — the SET ROLE demotion is no
longer NEEDED, because the credential is already bound.

The interesting part was a failure I caused and then diagnosed: two tests went
red. One was a fixture typo of mine. The other was real and instructive — the
never-set-GUC test opened its OWN connection hardcoded to `POSTGRES_USER` and
demoted it only when the store had an acting role. Once the store's credential
became unprivileged there was nothing to demote, so that test connection ran as
a raw superuser and read a row. It surfaced as a boundary failure that was
really **the test out-privileging the thing it was testing**. The change didn't
break the boundary; it broke a test that had been quietly relying on a superuser
being demoted for it.

**Unified data governance without moving a file (ADR-0053).** Arya spotted the
`realdata/` vs `data/` clutter. Merging them is the wrong move: the evidence
registry pins those panels AND their sha256 (52 hash pins, made
cross-platform-stable after CI caught a CRLF/LF mismatch), the
forecast/leakage/teardown suites read those exact paths, 54 files reference them.
The inconsistency actually worth closing was that `realdata/` held real
TLC/MTA/Chicago data with NO declared rights while `data/` refuses a byte
without one. Five sources now carry governance manifests at their existing
paths — and deliberately no `.acquired.json`, because these never went through
`acquire()` and writing one would forge a free-space guard, quarantine and
checksum promotion that never happened.

**The declutter audit's honest answer was "not much".** Zero tracked
`__pycache__`, an 81:79 code-to-test ratio, all 51 ADRs live, no dead code worth
archiving. `kaggle/` in particular must NOT be archived — it holds
transfer-learning results where the NEGATIVE results were deliberately kept as
evidence, and archiving them would quietly delete part of the honesty record.
Scope was held to what was actually redundant (four merged outreach staging
CSVs) rather than expanded to justify the exercise.

## 2026-07-25 (later): tranche 3 — six programs deepened, two more vacuous-test defects

Ground through the remaining gap list. Suite **976 -> 1248**, audit clean, CI
green, ADRs 0047-0051.

- **A — the scheduling family** (ADR-0047, 101 tests). Block / RunPiece /
  DeadheadSegment, which is what actually stood between Program B and TODS/NeTEx
  -- not adapter difficulty, a missing canonical home. `RunPiece` is one row per
  (run, piece), NOT per run: TODS gives a run no attribute of its own, so a
  `runs` table would hold nothing but an id and be a second place for the same
  fact to disagree. `DeadheadSegment`'s field names are deliberately the
  teardown's own `VehicleSegment` names, so a stored segment maps field-for-field
  with no translation. And RLS landed in the SAME packet as the tables -- the
  agent cited ADR-0037 having to fix that retroactively, so the recorded history
  is now changing behaviour.

- **D — tenant isolation** (ADR-0048, 150 tests). The finding: **RLS would have
  made an existing test vacuous.** ADR-0041's in-place-corruption test issues a
  raw `UPDATE`; under RLS with the wrong tenant in scope that matches ZERO rows,
  so "the past didn't change" becomes trivially true and the test keeps passing
  while proving nothing. It now asserts the tamper LANDED first. Both previously
  documented traps were closed by construction rather than luck -- the acting
  role asserted non-superuser AND table owner (ADR-0046 pre-emptively), and the
  RESET case asserted as an EMPTY STRING (ADR-0043).

- **E — serve-time drift** (ADR-0049, 23 tests). Closes a loop rather than adding
  a feature: ADR-0030 measured AAR intervals overcovering at 98.1% against a 90%
  target and isolated it to a winter->spring shift. That sat in a document. The
  runtime can now say it at serve time -- 8 of 15 features drift on exactly that
  window, with an exchangeable-split control reporting no drift, so it is a real
  shift and not a monitor artifact. The interval caveat cannot be separated from
  the number: `summary()` renders both on one line. Report, don't block, asserted
  field-by-field against the unmonitored path.

- **C — the open-data question, answered by measuring** (ADR-0050, 31 tests).
  Low hundreds of GB to ~1 TB of US open transit data exists; the slice that is
  rights-clean AND useful is ~250 MB. Acquired 286 MB under governance. The
  honest conclusion is that this is NOT the MoE regime -- demand forecasting is
  tabular, small-N per series, dominated by local structure -- and the repo's own
  evidence already said so: `transfer_control.py` kept both the negative and
  positive transfer results, and the leaderboard records the NTD temporal split
  LOSING to seasonal naive. What helps is more distinct OPERATORS, not more rows.

- **B — graduated repair** (ADR-0051, 24 tests). Arya's point, and it was right:
  quarantine-everything is useless when a partner sends a real vendor export. Ten
  unambiguous repair rules, each recording a `coerced` note naming the rule; and
  the refusal that matters -- `03/04/2026` is 3 April AND 4 March, so it is
  quarantined with both readings named. The date rules fire only when a component
  exceeds 12, which forces one reading; that is arithmetic, not a guess. Plus an
  ingest report that diagnoses CORRELATED missingness via a phi coefficient,
  because independent gaps shrink a sample while correlated gaps BIAS it -- the
  exact thing ADR-0039 hit on real TLC data.

- **M — the TS SDK had drifted 835 lines** with no gate watching it, while Python
  has had a contract-drift check since ADR-0027. Same class of error, other
  language, no guard. Gate added to the TS job.

Two process notes worth keeping. The messy-data agent was stopped mid-packet with
its code complete but no tests and no packet record; I finished both, and two of
my own first test assumptions were WRONG (that `headline` was a method, and that
a space-separated ISO timestamp needed repair). I corrected them against observed
behaviour rather than bending the tests -- tests written from an assumed API are
how a suite ends up asserting fiction.

And the standing lesson from this tranche and the last: **"all tests still pass"
is a weak signal immediately after a boundary change.** Three of the seven
defects found across both tranches were tests that would have kept passing while
proving nothing.

## 2026-07-25: the six pilot-blocking items — and three defects worth the tranche

Completed items 1-6 of the pilot-conversion list, ordered by dependency rather
than program letter, as six packets across two waves. Suite **781 -> 976**,
audit clean, CI green. ADRs 0041-0046.

What landed: a canonical home for `vehicle_ref`/`run_ref` (the field the whole
deadhead teardown depends on, which previously could not be persisted at all);
Program D persistence; RLS on the containerized PostGIS store; the teardown and
export-validation exposed over HTTP/SDK; and evidence packs that re-derive a
teardown rather than re-reading it.

But the tranche earned its keep on three defects, not the features:

- **`redact_pack` did not redact.** It masked payload keys in `raw_events` and
  left the same values in `pack.evidence`, which embeds payloads -- so the pack
  built *specifically to be shareable* still carried what it claimed to have
  removed, and the failure was silent. Found by the teardown-evidence packet,
  which deliberately **omitted** the assertion rather than writing a green test
  that asserted around a known leak. Fixed the class, not the instance: masking
  now follows the data recursively, and verification re-derives the redaction
  claim, so a pack claiming a redaction it never performed fails `reverified`.
  The fix's tests were checked against the old code -- 8 of 11 fail there.

- **The PostGIS container credential is a superuser.** The image bootstraps
  `POSTGRES_USER` with `rolsuper` and `rolbypassrls`, and superuser bypass is
  checked *before* FORCE. Applying RLS as that credential would have installed a
  boundary binding nobody: policies present, tests green, data unprotected --
  the exact false green `rls_postgres.sql` warns about for table owners, one
  privilege level up. Fixed with an unprivileged NOLOGIN owner role, and proven
  non-vacuous by mutation: no-op the role switch and 16 of 21 tests fail,
  including all three spatial ones. ST_DWithin is confirmed tenant-scoped --
  geometry is not a way around the policy.

- **ADR-0040's own platform clause broke deny-all.** `OR tenant_id = PLATFORM`
  is true whatever the GUC says. The implementing agent built it as written,
  refused to redesign unilaterally, and pinned the exposure in a test saying
  tightening it belonged in a new ADR -- so it forced the decision instead of
  making it. I tightened it (ADR-0043). My first fix was *also* wrong: after
  `RESET`, `current_setting(name, true)` returns the **empty string**, not NULL,
  so `IS NOT NULL` did not deny. The other policies survive that only
  incidentally, because `tenant_id = ''` is false for any real UUID. The test
  caught it; the prose never would have.

One process failure of mine, recorded because it nearly shipped: I used
`git add packages/core/` -- a directory sweep -- while a concurrent agent was
mid-write in that directory, and pulled its unfinished work into another
packet's commit. HEAD imported a symbol that did not exist at that commit. Caught
it because the commit's file list did not match the packet's owned paths,
amended before pushing, and used explicit file paths for the rest of the session.
File-level ownership means file-level `git add`.

Phase 4 remains pilot conversion, not frontier. J/K/L are still parked: they need
compute and a demand signal that does not exist, and completing programs is not
one of ADR-0026's three triggers for the polyglot rewrite.

## 2026-07-24: outreach went out, then built what it promised

Two halves to this session. First, outreach: rebuilt the cold-email approach
around a **peer-relative** hook (an agency's national rank among operators its
own size) instead of reciting their own filed deadhead figure back at them —
they already know that number; what they can't see is where they sit against
185 peers. Researched 58 verified contacts (every address read off a primary
source, nothing pattern-guessed, broker-only addresses rejected). Sent 15:
4 startup/integrator and the 11 strongest agency findings, ranks 1st–12th.
Anne Arundel County auto-replied in 11 seconds promising a human within two
business days — which also settled the deliverability question, since
auto-responders only fire on delivered mail.

Then the part that mattered more. Those emails contain the sentence *"I can
show you which hours and which runs."* **NTD is annual aggregate and cannot
answer that.** We had made a promise with nothing behind it, so three packets:

- **H — deadhead teardown** (ADR-0039, 35 tests). Localises empty vehicle-time
  to hour-of-day, day-of-week and run. Demonstrated on a real TLC week: 66,940
  segments, **8.89% of vehicle time empty**. Two findings justify the whole
  thing: the highest-*rate* and highest-*volume* empty hours are **different
  hours** (04:00 at 10.98% vs 22:00 with the biggest absolute pile) — the exact
  distinction an annual percentage destroys — and *correlated missingness* is
  real: re-keying on a nullable id put 10,918 segments into `unattributable`
  whose empty time is **exactly zero**, because operators omitting the base also
  omit the on-scene timestamp. Dropping null-id rows would have silently removed
  real vehicle minutes from every denominator. The refusals matter more than the
  number: `avoidable_share` has no default, `is_guaranteed_saving=True` raises,
  `causal_proof=True` raises, and `DataProvenance` has **no "operator" value**.
- **C+B — operator intake** (ADR-0038, 107 tests). The path from "yes" to data:
  field list, formats, retention, and an adapter that **fails closed on PII
  before any other validation**. `docs/OPERATOR_DATA_INTAKE.md` opens by telling
  the agency plainly that we have no customers and *"you would be the first"*.
  It surfaced a genuine canonical gap: `vehicle_ref`/`run_ref` — the field
  deadhead measurement depends on — has no canonical home and cannot be
  persisted to MilexiumDB.
- **A+C — canonical debt** (ADR-0037, 36 tests, 0 skipped). `DecisionAlternative`
  had a table since v0.1 that neither store ever touched; `StopTimeObservation`
  was unpersistable. And a **security defect I shipped in ADR-0035 and missed in
  review**: both observation tables were tenant-scoped with **no RLS policy at
  all**, because they were added to the schema after `rls_postgres.sql` was
  written. Now ENABLE + FORCE, with a test that lifts FORCE to watch the
  boundary collapse. The RLS tests ran against real Postgres — proven, not
  assumed.

Also decided the long-open `ModelVersion.tenant_id` question (ADR-0040):
a **reserved platform tenant**, rejecting nullable `tenant_id` because a
nullable tenant column is invisible to `tenant_id = GUC` and the first consumer
that forgets the special case gets a silently wrong answer. The policy is
deliberately asymmetric — any tenant may *read* platform models, none may write
one. Decision recorded; implementation deliberately left as its own packet
rather than half-landed.

Suite **603 → 781**, audit clean. Phase 4-as-written (J/K/L) stays parked:
it needs compute and a demand signal we don't have, and the honest next move was
backing the promise we'd already made.

## 2026-07-24 (night): Phase 3 COMPLETE — D + G gate cleared, canonical gap closed, estate on MinIO

Finished Phase 3 by dispatching the remaining work as four parallel packets on
disjoint owned paths (`packages/core` / `packages/verify`+`architecture/formal` /
`packages/canonical`+`packages/connect` / `packages/estate`). Reviewed every
agent's actual code, not just its report, and re-ran the headline measurements
myself. Suite: **603 passed, 0 failed** (513 → 603).

- **D — adaptive memory** (`packages/core/`, ADR-0034, 52 tests): a leakage-safe
  point-in-time `FeatureStore` whose one invariant is a *strict* `<` as-of read
  (a value stamped exactly at label time t is never visible) — proved
  mechanically by future-corruption on the REAL Access-A-Ride daily panel at
  three cutoffs, the same discipline `realdata/leakage_audit.py` applies to the
  training pipelines, now a runtime store. Plus a champion/challenger/canary
  `PromotionController` where the evaluated gate is the *only* path to champion
  (every verdict recorded, rollback stack), and a drift service (PSI + KS +
  two-sided CUSUM). The real-data proof point: the March-2020 COVID collapse is
  detected as a downward change-point, while a random exchangeable split of
  stable-year 2023 correctly does not flag.
- **G — formal invariants** (`architecture/formal/`, `packages/verify/formal.py`,
  ADR-0033, 10 tests): five genuinely machine-checked properties via the free
  z3 (installed, pinned as the `formal` extra, and wired into CI so the proofs
  RUN there rather than skip). S1 terminals-are-sinks, S2 irreflexive, S3
  acyclic, S4 no-dead-end on the ServiceRequest lifecycle; H1 hash-chain
  tamper-evidence. Every result is a solver verdict (`unsat` of the negation,
  or a constructive `sat` witness), never a Python assert. Independence is
  preserved the ADR-0028 way: the provers transcribe the spec BY HAND and never
  import `packages.canonical`; a single runner-side consistency check asserts
  the transcription equals `SERVICE_REQUEST_TRANSITIONS`, and a negative control
  flips one edge to prove that tie is load-bearing. H1 is honestly conditional
  on an explicit collision-freeness axiom — dropping it makes the theorem `sat`
  again, which the test asserts. It does **not** claim to prove SHA-256.
- **A + C — the ADR-0031 canonical gap, CLOSED** (ADR-0035, 46 tests): added the
  request-independent `VehicleObservation`/`StopTimeObservation` family with a
  real PostGIS `geometry(Point,4326)` column + GiST index — kept OUT of the
  portable base DDL (SQLite-safe, verified) in a separately-versioned
  `sql/postgis_postgres.sql`, exactly the split `rls_postgres.sql` uses, and
  applied by a new `observation_store.py` against the containerized PostGIS on
  5433. Re-mapped the GTFS-RT adapter onto it. Measured on the real samples:
  MBTA went from 251 `Outcome`s + **314 quarantined** to **567/567
  `VehicleObservation`s, 0 quarantined**, with **no synthetic `request_id`
  anywhere**. The spatial `ST_DWithin` round-trip genuinely ran (not skipped).
  Nice detail the agent got right: source `vehicle_id`/`trip_id`/`stop_id` stay
  plain strings, not canonical typed ids — they name another agency's entities,
  and typing them would repeat the very category error the packet removes.
- **C — estate raw zone backed by MinIO** (ADR-0036, 7 tests): `acquire()` now
  additively mirrors each promoted object into the free, already-running MinIO
  under **the same sha256 that is the estate's own content address** (mismatch
  raises), recording the key in the catalog. Local disk stays default and
  byte-for-byte unchanged when the store is off; the round-trip test ran live.
  No paid-cloud SDK or credentials, per the founder's hard constraint.

Centrally (mine, not the agents'): pinned `z3-solver` as a `formal` extra and
installed it in CI; exported the two new entities to the generated `contracts/`
layer (now 14 entities) so external producers have a schema to map onto — the
contract-drift check that would otherwise have bitten on CI. Two long-standing
blockers moved from "available" to "actually in use": PostGIS now carries a real
geometry column, and MinIO now backs the estate.

Phase 3's gate was D + G; both are built, integrated, tested, and committed.
Everything remains **Demonstrated** — the Validated gate still needs a consented
operator, and no amount of this work crosses it.

## 2026-07-24 (night): infra live — compose stack up, object storage + PostGIS cleared

WSL2 + Docker Desktop came up on the dev machine (Docker Engine 29.6.2). Brought
up the `infra/compose` stack — PostgreSQL 16 + **PostGIS 3.4**, **MinIO**
(S3-compatible), and an OpenTelemetry collector, all healthy. The Postgres
container is on host port 5433 so it coexists with the native PostgreSQL 17
(5432, ADR-0006); secrets live in a gitignored `infra/compose/.env`.

Wired the **first real object-storage path**: `packages/estate/object_store.py`
`MinioObjectStore` — content-addressed (key == sha256), so storage dedups and a
`get` verifies the bytes hash back to the key (tamper/corruption-evident on
every read, same stance as the event-log hash chain). A round-trip conformance
test puts/gets/dedups a real object against the running MinIO and proves a
corrupted object is rejected (4 tests); it skips cleanly when `minio` (the
optional `objectstore` extra) or the container is absent, so CI stays green.

Two long-standing blockers **cleared at the dev level** (ADR-0032): object
storage (was "no S3 credentials") is now **Exists (dev)**, and PostGIS (was
"not installed") is available. Production still needs real cloud credentials +
per-tenant isolation; pointing `PostgresCanonicalStore` at the containerized
PostGIS is a later additive step (the native instance still serves the tests).

Also: Phase 3 (E forecast depth + B Connect breadth) landed earlier today —
committed, pushed, CI green on HEAD.

Renamed from TransitPulse to Milexium on 2026-07-22 (see entry below). Entries
dated before the rename refer to the company as TransitPulse throughout,
unchanged, because this file is an append-only historical record.

## 2026-07-24 (night, later): Phase 3 begins — forecast depth + Connect breadth; CI fixed

First fixed the GitHub Actions CI, which had failed: root cause was
`hashFiles()` in a job-level `if` (invalid — the whole workflow failed to
compile, 0 jobs), plus two Linux-runner-only test bugs the run surfaced — the
estate free-space tests tripped the runner's 20 GB floor (passed
`free_floor_gb=0`), and, more importantly, two committed CSV panels hashed
differently on Linux (LF) vs Windows (CRLF) so the evidence-registry sha256
check failed. Fixed that correctly: marked the panels `binary` in
`.gitattributes` (one canonical LF form everywhere) and recorded the portable
LF hashes — the registry verifier had caught a genuine cross-platform
reproducibility defect. Python + Rust jobs now pass; TS passes too.

Then dispatched Phase 3 (Arya's pick: E forecast depth + B Connect breadth):

- **E — forecast depth** (`packages/forecast/conformal.py`): serve-time
  split-conformal prediction intervals, with the quantile index matching
  `realdata/train_real_models.py` exactly (so it reproduces the committed
  model-card half-widths). Global/unconditioned, justified by the repo's own
  null Mondrian result (RND_QUESTIONS Q4). All four real zone-hour models
  (AAR/Chicago/MTA bus/MTA subway) now serve forecasts through the runtime,
  each with its correct per-feed feature schema (only the trailing zone column
  differs). The honest, diagnostic finding: committed intervals overcover (AAR
  98.1% vs 90% target), and refitting conformal on a random *exchangeable*
  split of the same window recovers ~90% — isolating the overcoverage as
  winter→spring distribution shift, not a method flaw, empirically confirming
  the repo's own open Q4. A conformal interval is distribution-free only under
  exchangeability, not a per-forecast guarantee. ADR-0030; 28 tests.
- **B — Connect breadth** (`packages/connect/gtfs_realtime.py`): a
  GTFS-Realtime adapter mapping VehiclePosition/TripUpdate → `Outcome`, with
  real MBTA (.pb, 564 vehicles) and Apache-2.0 google (.asciipb) samples
  acquired through the estate. The headline output is a genuine **canonical-
  model gap** it surfaced: GTFS-RT is operational telemetry keyed by
  (trip,stop,vehicle) with no rider request, but every canonical entity is
  rider-request-keyed — so it maps only via a synthetic request_id placeholder
  + heavy semantic loss. Finding: the canonical model lacks a first-class,
  request-independent operational/telemetry entity (VehicleTelemetry/
  StopTimeObservation) — a Program A follow-up. TODS/NeTEx deferred for the
  same reason rather than half-built. Rights handled carefully (Apache-2.0
  sample as the clean anchor; MBTA flagged with an unverifiable-commercial-
  clause caveat). ADR-0031; 20 tests.

Wired GtfsRealtimeAdapter into `packages/connect/__init__.py`; the B agent
added `gtfs-realtime-bindings` + `protobuf` to pyproject. Suite: **509 passed**
(461 → 509). Phase 3 D (feature store/champion-challenger/drift) and G (formal
invariants) remain. Also gave Arya the WSL2-fix + Docker-install steps so the
compose stack (Postgres/PostGIS/MinIO) + first real object-storage path can be
wired once Docker is up.

## 2026-07-24 (night): polyglot foundation — Chris's architecture, adopted and phased

Chris sent a detailed brief to evolve Milexium into a three-language platform
(Rust data plane / TypeScript control plane / Python science, contracts-first,
full service decomposition with gRPC/Temporal/Kafka/object-storage). My honest
read: the architecture is genuinely strong as a *destination*, but building the
whole thing now would re-open the "infrastructure before demand" trap for a
pre-traction team with a YC deadline and no measured bottleneck. Arya chose the
**synthesis** (my recommendation): do the cheap, reversible, strategy-advancing
parts now; defer the heavy rewrite behind a real trigger. Recorded in ADR-0026
as adopted-and-phased with the full deferred list reasoned out (not rejected),
so when a trigger fires the decision is already made.

Built and integrated this tranche:
- **`contracts/` layer** (ADR-0027): JSON Schema (12 canonical entities) +
  OpenAPI (7 endpoints) generated from the Python source of truth so nothing is
  hand-duplicated; a proto seed + Buf codegen deferred; a CI drift-check keeps
  the artifacts from diverging (forced LF for cross-platform stability).
- **Rust workspace + evidence-verifier crate** (ADR-0028): an independent Rust
  reimplementation of the hash-chain verifier, **byte-for-byte differential
  parity with Python** — including a full replication of Python's `ensure_ascii`
  JSON escaping with UTF-16 surrogate pairs (proven on a `"café 🚌 Ω"` payload).
  The two verifiers produce identical violations on clean, tampered, non-ASCII,
  and multi-aggregate chains. Honest limitation recorded: exotic float
  formatting isn't covered (no float payloads exist in the domain). 11 Rust +
  6 differential tests; cargo fmt/clippy/test clean.
- **TypeScript SDK** (`@milexium/sdk`, ADR-0029): a strict-mode client whose
  types are generated from the OpenAPI contract (not hand-duplicated). Used npm
  (corepack pnpm hit EPERM without admin) + Node 24 native TS type-stripping;
  13 tests. Fixed the CI TS job to npm accordingly.
- **Infra**: a Docker Compose dev stack (Postgres/PostGIS + MinIO + OTel) ready
  for when Docker/WSL2 is fixed, and a path-aware GitHub Actions CI (Python now;
  Rust/TS jobs auto-activate via hashFiles guards).

Reviewed both agents' code directly and ran the gates myself: `cargo test` (11)
+ the 6 cross-language parity tests RUN (not skip) and pass; `py -3 -m pytest
packages/ conformance/` → **461 passed** (455 → 461). The core verifier now has
two independent implementations that agree byte-for-byte — a real, checkable
strengthening of the verifiability moat. Python stays first-class and the
reference; every future migration is gated by differential parity against it.

## 2026-07-24 (later still): Phase 2 complete — evidence artifacts (leaderboard + registry)

Finished Phase 2 with two parallel packets packaging the repo's real numbers
into reproducible, third-party-checkable artifacts:

- **Forecast leaderboard** (`benchmarks/quality/forecast_leaderboard.*`): real
  R² vs each model's seasonal-naive baseline (AAR 0.986 vs 0.923 naive, −64%
  MAE; Chicago/MTA in the 0.95-0.97 range), every value traced to its source
  json-path (the test re-reads the source and compares, proving traceability
  not hand-copying). Does NOT hide losses: the NTD temporal split loses to
  naive on R² (0.885 vs 0.972), shown as `beats_naive_on_headline: false`; the
  weather-barely-helps and calendar-only-ties-naive findings are recorded. No
  cross-model ranking (R² not comparable across grains). Transformer excluded
  (mirrors MODEL_CARDS "not shipped").
- **Evidence registry** (`tools/build_evidence_registry.py`,
  `artifacts/evidence-registry/`): 20 claims + 8 provenance manifests, each
  value pinned to source + baseline + limitation + status label; a
  `verify_evidence_registry()` re-checks that every source exists and every
  recorded panel sha256 matches. Generated, never authored — anti-fabrication.

Doing its job, the registry surfaced real cross-document drift a hostile
reviewer could pick at (none a fabrication): `realdata/README.md` prose
headlines a different conformal variant (97.8% Mondrian) than MODEL_CARDS
(98.11% decile) and a rounded MAE (20.4 vs the committed 20.12); NTD MAPE units
differ (fraction vs ×100). Flagged for a doc-reconciliation pass (README →
committed metrics as single source of truth) and recorded in IMPLEMENTATION_
STATUS as a recommended follow-up — left to the product owner since it's a
which-variant-to-headline judgment. Wrote ADR-0025.

`py -3 -m pytest packages/ conformance/` → **455 passed** (439 → 455: +7
leaderboard, +9 registry); registry self-verifies clean; audit clean.

Phase 2 (undeniable public evidence) is complete: a runnable real-data demo, a
published-benchmark solver result (proven optimum reached), a traceable
forecast leaderboard, and a machine-checkable evidence registry — the checkable
proof-without-traction set. Everything Demonstrated; the Validated gate still
needs a consented operator.

## 2026-07-24 (later): Phase 2 begins — proof-first (golden-path demo + DARP benchmark)

After Phase 1, Arya raised the real strategic bind: can't get customers to look
pre-traction, aiming for YC Fall 2026, so the product itself has to be the
proof — a "Palantir for transport" intelligence layer. Reframed the pitch:
the differentiator isn't grandiosity, it's **verifiable rigor** (every number
independently checkable, tamper-evident, reproducible), which is more YC-shaped
and, unlike "intelligence layer," actually checkable. Reprioritized the roadmap
so Phase 2 is proof-first — undeniable, stranger-runnable public evidence that
substitutes for traction — with breadth moved to Phase 3 and frontier to
Phase 4. Two parallel packets landed:

- **Golden-path demo** (`demo/golden_path.py`, `py -3 -m demo.golden_path`):
  one command drives the whole loop on REAL public data — ingest 8 real NYC TLC
  trips → serve a real ~55.5-booking forecast from the hash-verified AAR booster
  → decide + human override on the hash-chained ledger → build + independently
  re-verify an EvidencePack → baseline-vs-Milexium replay → export. Labels its
  own real-vs-synthetic boundaries in-output and does NOT cherry-pick: served
  +2 / denials −2 favour Milexium while utilization favours the baseline (the
  service-level/utilization tradeoff, shown). Real: demand + forecast.
  Synthetic (labelled): fleet + scheduling assumptions. Modelled: replay.
- **DARP solver benchmark** (`packages/decide/darp_*`, `benchmarks/quality/`):
  Arya asked to "push for competitive numbers" — honored by building a genuinely
  stronger solver (pure-Python regret insertion + large-neighbourhood search,
  v0.2, no ortools) and reporting the REAL measured result. On the published
  Cordeau instances it **reached the proven optimum on a3-18 (0.00% gap, 18/18
  served)** and was 7.97% above optimum on a2-16, every solution validated by
  both the routing-aware and the original independent feasibility checker with
  an independently recomputed objective. The summary states plainly it is "NOT
  a state-of-the-art DARP solver" and makes no claim to beat published solvers —
  the honesty is the credibility.

Integrity verified in code, not just from reports: the new DARP checker leaves
the original `check_feasibility` untouched (appended only) and imports no
solver; the benchmark recomputes the objective independently. The benchmark
agent's own final report was truncated (a ~63-minute run), so I inspected the
tree, ran the suite (439 passing), and confirmed the honest results + the
checker independence directly. Wrote ADR-0023 (demo) and 0024 (benchmark).

Honest limitations recorded: the demo's fleet is synthetic; the benchmark
counted only 2 instances (hit its time budget — a broader sweep is a
straightforward follow-up). Both remain Demonstrated; the Validated gate still
needs a consented operator. Phase 2 items 3-4 (forecast leaderboard, evidence
manifests) are next.

## 2026-07-24: Phase 1 complete — pilot-ready runtime (5 parallel packets)

After merging the completion roadmap into IMPLEMENTATION_STATUS.md (reachable
pilot-ready target vs unbounded full blueprint; the pilot gate), Arya said to
finish Phase 1. Dispatched all five Phase-1 capabilities as parallel packets on
disjoint package paths; all landed, reviewed in code, and integrated at 390
passing tests (baseline 212 + 178), audit clean:

- **M — HTTP/OpenAPI API + SDK methods** (`packages/api/`, `packages/sdk/`):
  `MilexiumClient` gained `forecast()` and `export_pack()`; a FastAPI app
  mirrors the SDK loop over HTTP with an auto-generated OpenAPI contract — the
  language-neutral surface other software integrates against. Honestly excludes
  ingestion/forecast from HTTP (adapters/model files don't belong as JSON) and
  leaves auth/gateway Specified. A tampered chain surfaces verified=false over
  HTTP; an evidence pack re-verifies from the HTTP response bytes alone.
- **C — PostgreSQL row-level security** (`sql/rls_postgres.sql`): database-layer
  tenant isolation with `FORCE ROW LEVEL SECURITY` on all 12 tenant-scoped
  tables. The crux handled correctly — the `milexium_dev` role owns the tables,
  and a plain `ENABLE` lets the owner bypass RLS (false green); `FORCE` binds
  the owner. Proven with a raw `SELECT` under a different tenant's GUC returning
  zero rows, and `NO FORCE` making the owner see everything again. Unset session
  is deny-all.
- **H — replay + comparison** (`packages/replay/`): info-cutoff-safe replay
  (sole authority = canonical `known_as_of`) + baseline-vs-Milexium metric
  comparison. "Modelled comparison, not causal proof" enforced three ways in
  code (single-sourced note, a validator that raises on `causal_proof=True`,
  structural observed/simulated provenance); no dollar/savings field exists.
- **I — period/incident/procurement evidence bundles** (`packages/evidence/
  packs.py`): multi-decision bundles reusing the single-pack machinery; each
  `verify_*` recomputes the outer checksum AND re-runs every embedded pack's own
  hash chain, so a re-anchored outer checksum is still caught by the inner
  chain. Procurement bundle honestly separates available / not-yet-available
  (needs legal/ops) items with no compliance claims. Cross-tenant bundles
  refused at build time.
- **F — Decision program slice** (`packages/decide/`): Decision IR + a pure-
  Python grid-exact branch-and-bound solver (greedy fallback) with honest
  status — a timeout incumbent is structurally never labelled OPTIMAL — plus an
  **independent** feasibility checker. Independence verified in code: the
  checker imports only `canonical.vocab` + `decide.ir`, never the solver; the
  solver self-audits via the checker before returning (one-way dep). Adversarial
  tests hand-build solutions the solver never produced. Strictly additive — does
  not touch `reference_agency/` or the founder-owned YC scheduler, and
  `packages/decide/__init__.py` says so explicitly. No `ortools`/new dependency
  added.

Wrote ADRs 0018-0022 (C kept 0018, which it had baked into its files). All five
packets stayed within their owned paths — verified the working tree was exactly
the disjoint packet paths before integrating, and confirmed the two claims that
mattered most (F's solver→checker one-way import; C's FORCE-RLS blocking the
owner) directly in code, not just from the reports.

Phase 1 is complete; every capability is **Demonstrated**, none Validated. The
critical path is now landing a design partner — Phase 1 makes that materially
easier (HTTP integration, DB-layer isolation, handable verifiable evidence) but
no further code crosses the Demonstrated→Validated gate. Phase 2 (breadth:
GTFS-Realtime, feature store, serve-time uncertainty, a formal invariant or two)
is the next block if/when Arya wants it.

## 2026-07-23 (night): forecast runtime + evidence-pack export

Finished the two next-unblocked strategic targets, built directly (not via
subagents — focused enough to keep quality control at the finish line):

- **Program E — Forecast runtime** (`packages/forecast/`): a `ForecastRuntime`
  that resolves the champion model for a task from the Program D registry,
  loads its real XGBoost booster, **hash-verifies the artifact bytes against
  the registered `ModelVersion.artifact_hash` before predicting** (refuses a
  stale/swapped/corrupted file, and refuses a model with a non-hash
  placeholder like the NTD `NOT_COMPUTED` one), predicts on a point-in-time
  feature row (missing feature → error, never silently zero-filled), and emits
  a canonical `ForecastVintage`. Confirmed end-to-end on the *real* committed
  Access-A-Ride booster — served a plausible ~54-booking forecast for a
  Monday-8am summer borough-hour. This turns "we have good models" into "the
  runtime serves forecasts." Honest: Demonstrated on real *aggregate* data;
  aggregate forecasts don't validate individual dispatch, and a vintage
  interval is a model interval, not a probability (blueprint 01).
- **Program I — evidence-pack export** (`packages/evidence/export.py`): a
  portable, JSON-serializable `EvidencePack` for one decision that a third
  party re-verifies *without* Milexium — `verify_evidence_pack` recomputes the
  bundle checksum and re-runs the hash chain from the pack's own embedded
  bytes, trusting no manifest claim. Proven honest by tests: altering content
  is caught by the checksum; even an attacker who re-anchors the checksum after
  tampering is still caught by the inner chain. `redact_pack` masks sensitive
  payload fields for sharing but is explicit that masking breaks per-event
  chain re-verification and is field masking, **not** HIPAA de-identification
  (blueprint 10). This is the "undeniable operational evidence you can hand a
  partner" artifact.

Wrote ADR-0016 (forecast runtime) and 0017 (evidence-pack export). `py -3 -m
pytest packages/ conformance/` → **212 passed** (202 → 212: +5 each). Audit
clean.

With this, all 7 strategic-spine programs (A, B, C, D, E-slice, G, I, M) have
working v0.1 slices AND the two capabilities that make the go-to-market
concrete — real forecasts served through the runtime, and a verifiable
evidence artifact — now exist. Deliberately left as a clean follow-up (not
done, to keep the just-committed SDK surface stable): exposing
`forecast(...)` and `export_pack(...)` through `MilexiumClient`.

Attempted to review Chris's first-pass website at https://milexium.com against
the truth/claims guardrails from blueprint 01/10, but the site is
client-side-rendered and a fetch returned only the app shell, not the rendered
copy — so no actual review was possible. The guardrail checklist (no
HIPAA/ADA/SOC2-compliant claims, "tamper-evident" not "immutable", no
savings/customer claims until a pilot, keep forecasting=real vs
scheduling=demonstrated separate) stands for whenever the copy can be read as
text.

## 2026-07-23 (evening, later): standards adapters + SDK — the integration surface

Three parallel packets against the estate + canonical/connect foundations,
all landed and integrated in one review pass:

- **TIDES adapter** (`packages/connect/tides_trips.py`): maps TIDES
  `trips_performed` (the open demand-responsive-transport trip standard) onto
  `ServiceRequest`, built against the real TIDES schema acquired into
  `data/standards/`. Notable honest call (ADR-0014): TIDES has no rider
  request timestamp, so `requested_at` is anchored to `service_date` at
  midnight — an obviously-synthetic day-granularity placeholder that
  self-documents as "request instant unknown" and preserves `requested_at ≤
  scheduled ≤ actual` ordering — rather than reusing `schedule_trip_start`
  and falsely asserting zero advance-notice booking.
- **GTFS-Flex adapter** (`packages/connect/gtfs_flex.py`): maps a real
  GTFS-Flex on-demand feed (City of Aspen "Downtowner", acquired this
  session) onto `ServiceRequest`. The standout: GTFS-Flex's
  `start/end_pickup_drop_off_window` map directly onto
  `RequestTimes.negotiated_window_start/end` — the *first* adapter in the repo
  to populate the negotiated-window field from real data (reference-agency and
  TLC both correctly left it unset). Concrete evidence that the canonical
  `RequestTimes` contract actually fits the demand-responsive-transport domain
  it was designed for. Honestly records that a Flex feed describes bookable
  service *availability*, not observed demand, so downstream must not count it
  as demand.
- **MilexiumClient SDK** (`packages/sdk/`): the Program M integration surface —
  one import (`from packages.sdk import MilexiumClient`) drives the whole loop
  ergonomically: `in_memory()` → `ingest(adapter, rows)` →
  `record_decision`/`record_override` → `evidence_for(id)` returns a verified
  `EvidencePacket`. Decoupled from concrete adapters (imports only the generic
  `parse_batch`), so a new adapter needs zero SDK change. Runnable ten-minute
  quickstart. This is what makes "other software integrates Milexium" real
  rather than aspirational — previously the biggest gap on the strategic path.

Wired all four adapters (including the previously-unwired TLC one) into
`packages/connect/__init__.py` during integration. Wrote ADR-0014 (standards
adapters) and ADR-0015 (SDK facade) for the flagged decisions. Reviewed the
SDK and both adapters' actual code — confirmed the negotiated-window and
TIDES time mappings are real in the source, not just claimed. `py -3 -m
pytest packages/ conformance/` → **202 passed** (159 → 202: +16 TIDES, +19
GTFS-Flex, +8 SDK); audit clean.

Five adapters now map five structurally different sources onto one
`ServiceRequest` contract. Program M has a first real slice. Next
dependency-unblocked, strategy-relevant targets: a Forecast-runtime wrapper
around the existing real `realdata/` models (Program E — makes the real
forecasting reachable through the same runtime/SDK), and a
decision-evidence-export surface (Program I extension — the "hand a partner a
verifiable evidence pack" capability).

## 2026-07-23 (evening): repositioning + governed data estate

Arya set the strategic frame explicitly: rather than wait on a large transit
agency to prove Milexium works (outreach is brutally hard pre-YC), build
enough product to generate undeniable operational evidence independently from
public data, win smaller customers with it, and climb upward — and reposition
Milexium as "the transport intelligence layer that converts operational data
into forecasts, feasible plans, and auditable decisions," a decision *runtime
other software integrates*, not just a dashboard agencies log into. This is
consistent with the expansion blueprint's own north star (blueprint 01,
"model-agnostic decision infrastructure"), so it's a sharpening of direction,
not a pivot.

The instinct was "download all the data and technology." The formidable
version of that — and the one the blueprint itself mandates — is governed
acquisition, not a bulk pull: blueprint 17 says "No download enters the estate
without [a manifest: rights, checksum, purpose, quality tests, retention]" and
blueprint 20 says "Do not vendor upstream projects blindly." A governed,
rights-clean, reproducible estate is exactly what makes Milexium integratable
by other software; an ungoverned pile is not. So this tranche built the
governance, not the volume:

- **`data/` estate** (blueprint 17 zone layout): `catalog/` (committed
  governance ledger) + `raw/`, `quarantine/`, `standards/`, `networks/`,
  `canonical/`, `features/`, `simulation/`, `semantic/`, `experience/`,
  `benchmarks/`, `evidence/`, `scratch/` (gitignored, large/reproducible).
- **`packages/estate/`**: an `AcquisitionManifest` contract where rights
  *must* be declared (not "unknown"), and `acquire()` enforcing free-space
  check → quarantine download → checksum → content-addressed promotion →
  catalog record. Plus catalog inventory + free-space reporting.
- **Proved end-to-end on real, rights-clean, on-point data**: acquired a TIDES
  `trips_performed.csv` sample (Apache-2.0 — the demand-responsive-transport
  trip-level standard, maximally on-brand for paratransit) into
  `data/standards/`, and a Geofabrik DC OpenStreetMap extract (ODbL, 20.9 MB
  real routing data) into `data/networks/`. Free space reported 335.33 →
  335.31 GB across the two pulls; raw bytes gitignored, catalog records
  committed.
- **`third_party/VENDORING_PROCESS.md`**: the gate for the "download the
  technology" half — a review manifest (license/maturity/security/benchmark)
  + ADR required before anything lands, nothing vendored yet. Named the
  nearest real candidates (pgvector, OR-Tools) and why the frontier dossier
  tech (FHE, silicon, world models) is deliberately nowhere near the gate.
- ADR-0013; 5 new governance conformance tests (rights required, free-space
  guard fires before download, checksum mismatch leaves the object in
  quarantine and never in the trusted zone, clean acquisition catalogs real
  bytes). Full suite 159 passed; audit still clean.

Deliberately NOT done, and why: the 250 GB is not bulk-downloaded (every
future dataset is a queued rights-checked manifest, one command away — this is
how "every byte has a manifest" is enforced without a reckless pull that could
fill the disk or ingest unlicensed data); no dossier technology vendored. The
value banked here is the governance pipeline, not the ~0.02 GB it has so far
pulled through it.

Next planned tranche (the actual repositioning payload): standards adapters —
TIDES `trips_performed` → `ServiceRequest`, GTFS-Flex → `ServiceRequest` —
against the newly-acquired `data/standards/` corpus. These are the
vendor-neutral ingestion surface that makes Milexium a runtime other software
plugs into, and they extend the existing two-adapter Connect base (ADR-0007,
0011) toward blueprint 03's full standards-adapter set.

## 2026-07-23 (later still): expansion tranche 3 — B second adapter, D first slice, I verification folded in

Three more parallel packets, dispatched after Arya said "GO GO GO" to
continue past the tranche-2 checkpoint:

- **Program B, second adapter:** `packages/connect/tlc_trips.py` maps real
  NYC TLC FHVHV trip Parquet data (`realdata/raw_tlc/`, already downloaded
  for the forecasting pipeline) onto `ServiceRequest` — structurally
  different from the first adapter (columnar, pandas-null-typed, no rider
  identity at all, real observed schema drift across file vintages). Found
  and used real failure modes for quarantine tests: 108,898/20.16M null
  request times, ~600k rows with TLC's own unknown/outside-NYC placeholder
  zone codes. One genuine deviation from the original task brief, flagged in
  ADR-0011: TLC does carry a `wav_request_flag` (wheelchair-accessible-
  *vehicle* request), mapped to `mobility_device` with an explicit caveat
  that it's a vehicle attribute, not a direct statement of the rider's own
  device.
- **Program D, first slice:** `packages/core/` catalogs this repository's 5
  real, trained, evaluated models (`docs/MODEL_CARDS.md`) as `ModelVersion`
  registry entries with a closed task vocabulary (`forecast.demand`) and a
  simple per-task champion pointer. Every `training_data_manifest_hash` and
  `artifact_hash` is a real sha256 read from or computed against a committed
  file, cited per field — except NTD's artifact hash, honestly labeled
  `NOT_COMPUTED` because `realdata/model_ntd_monthly.py` never saves a
  booster file, rather than faking a hash. I independently re-verified one
  claimed hash against its source manifest myself before accepting the
  packet's work — exact match. Flagged a real contract gap in ADR-0010:
  `ModelVersion.tenant_id` is mandatory but these models aren't tied to any
  customer; a placeholder tenant id is a stopgap, not a resolution.
- **Program I, verification folded in:** extended `EvidencePacket` to
  aggregate schema conformance alongside the existing hash-chain check. The
  packet's own honest conclusion: for every real call path in this repo
  today, the schema check is close to a tautology (events arrive already
  Pydantic-validated), and it said so plainly rather than overselling the
  addition — then proved the one case where it isn't a tautology
  (`DecisionEvent.model_construct`, bypassing validation). State-transition
  verification could not be wired in at all: nothing in this repo's
  contracts yet records a `ServiceRequestState` sequence inside a
  `DecisionEvent` chain, so `state_check_applicable` stays honestly `False`
  rather than being faked — recorded as a structural gap in ADR-0012, not a
  shortcut.

Wrote three more ADRs (0010, 0011, 0012) during integration review, same
reasoning as tranche 2: agents flag decisions, the orchestrator numbers and
formalizes them centrally to avoid parallel-agent ADR-number collisions.

Deliberately did not dispatch a Program F (Decide/optimization) packet this
tranche — it would overlap with `docs/MASTER_ROADMAP.md`'s own Friday
OR-Tools scheduler task, which is Arya's directly-owned roadmap item, not
expansion-swarm territory. Two competing scheduler implementations with no
clear authority for the YC demo would be a real, avoidable risk.

Reviewed all three agents' actual code directly before integrating —
independently re-ran the full suite and re-verified specific factual claims
(a manifest hash, the real diff on already-committed evidence files) rather
than trusting self-reports alone. `py -3 -m pytest packages/ conformance/` →
**154 passed, 0 failed** (124 from tranche 2 + 30 new). `tools/
audit_repository.py` unaffected. Nothing in `realdata/` source,
`reference_agency/`, `ntd/`, `kaggle/`, `outreach/`, or existing `docs/`
content was touched by any of the three packets.

## 2026-07-23 (later): expansion tranche 2 — Programs B, C-Postgres, I first slices

After the Program A/G foundation checkpoint (below), Arya said to proceed
full steam and dispatched three parallel work packets against the versioned
A/G contract, each on a disjoint owned path:

- **Program B (Connect), `packages/connect/`:** a minimal adapter contract
  (`AdapterResult`/`QuarantinedRow`/`SemanticLossRecord`, exactly-one-outcome
  enforced by a Pydantic validator) plus one concrete adapter mapping
  `reference_agency/output/trips.csv` — a real, already-generated, but
  explicitly fictional 89,566-row source — onto `ServiceRequest`. Tokenizes
  rider identity via SHA-256; quarantines malformed rows (missing pickup
  date, invalid mobility-device value, out-of-range hour) instead of
  dropping or crashing; records every field the source has but
  `ServiceRequest` v0.1 doesn't as a semantic-loss entry rather than
  silently discarding it. Flagged one honest interpretive call: the source
  has one timestamp per trip, not five, so `requested_at` is filled and the
  negotiated/scheduled/predicted fields are left unset rather than guessed.
- **Program C continued (Postgres store), `packages/canonical/postgres_storage.py`:**
  a `PostgresCanonicalStore` mirroring `SqliteCanonicalStore`'s exact method
  contract, running against the PostgreSQL 17 instance installed earlier this
  session via the `milexium_dev` role (never the superuser). Applies
  `schema_v0_1.sql` completely unmodified. Test isolation uses a disposable
  per-instance PostgreSQL schema (`mx_<uuid>` + `DROP ... CASCADE`) rather
  than any shared fixture database — verified zero leftover schemas after
  repeated runs. New Postgres-backed tests skip cleanly (not fail) if
  `milexium_dev` isn't reachable, so the suite stays green on a clone without
  it provisioned.
- **Program I (Evidence/Experience IR), `packages/evidence/`:** an
  `EvidencePacket` that reconstructs, from an aggregate's recorded
  `DecisionEvent` history alone, what was known, proposed, considered as an
  alternative, approved/overridden, executed, and observed — plus the actual
  result of running `packages.verify.verify_chain` against it, so a tampered
  chain is visibly flagged (`integrity_verified=False`) rather than presented
  as trustworthy evidence. `build_experience_packet` refuses to run against
  an unverified packet. Flagged a real gap: `packages/canonical` has no store
  method for the `decision_alternatives` table `schema_v0_1.sql` already
  defines, so alternatives are read from a `RECOMMENDATION` event's
  `payload["alternatives"]` as a v0.1 convention, not a canonical contract
  change — recorded in ADR-0009 as something to reconcile once a real
  scheduler needs to write that table.

Formalized four more ADRs (0006 dedicated Postgres role — written before
dispatching, since it involved real credential setup; 0007 Connect adapter
contract; 0008 Postgres test-isolation strategy; 0009 Evidence IR
conventions) during integration review, since the three agents were
instructed not to self-author ADRs (to avoid three parallel agents colliding
on the same ADR number) and to flag decisions in their reports instead.

Reviewed all three agents' actual code and test output directly (not just
their self-reports) before integrating — confirmed the same test counts
independently: `py -3 -m pytest packages/ conformance/` → **124 passed, 0
failed** (92 from the first tranche + 32 new). `tools/audit_repository.py`
still passes unchanged. Nothing in `realdata/`, `reference_agency/` source,
`ntd/`, `kaggle/`, `outreach/`, or existing `docs/` content was touched by
any of the three packets.

Next planned tranche (pending checkpoint review with Arya): Program D
(Core/adaptive memory — task registry, feature contracts) and Program H
(Replay — exact/historical replay using `EvidencePacket` as its evidence
source) are the next dependency-unblocked programs per `SWARM_MANIFEST.yaml`.

## 2026-07-23: expansion kickoff — Program A/G foundation

A separate specification, `C:\Users\aryaa\Documents\Milexium Expansion plan`
(blueprint documents 01-20, `SWARM_MANIFEST.yaml`, a dossier of 80
technologies and 72 intelligence-layer projects), describes a long-term
platform architecture: canonical transport substrate, MilexiumDB, Core/
Forecast, Decide, Verify, Replay/Explain, Forge/Fabric, Runtime, Edge, and a
product/API surface, built through contract-driven parallel agent work
(programs A-M).

Arya directed implementing this now, in parallel with the YC deadline work in
`docs/MASTER_ROADMAP.md` rather than instead of it, with the instruction to
record everything here and stop at defined checkpoints rather than running
unattended to full blueprint completion. Before writing any code, the
conflict between the expansion's scope and the roadmap's explicit "scope kill
list until submission" was raised; Arya's call was to proceed with the full
expansion and treat the roadmap as the thing to protect, not the thing to
follow narrowly.

Infrastructure: this machine had no Docker, no working WSL ("Class not
registered" error), and no PostgreSQL. Arya asked what to install to remove
the hindrance; PostgreSQL 17 was installed natively via
`winget install --id PostgreSQL.PostgreSQL.17` and confirmed running as a
Windows service. PostGIS is not installed yet (ships separately) and nothing
in this repository talks to the new Postgres instance yet — see
`architecture/decisions/0004-sqlite-now-postgres-production.md`.

Built this session (all under new root directories `architecture/`,
`packages/`, `conformance/`, `benchmarks/`, `research/`, `third_party/`,
`ops/`, `workstreams/`, plus root `IMPLEMENTATION_STATUS.md` and
`pyproject.toml` — nothing in `realdata/`, `reference_agency/`, `ntd/`,
`kaggle/`, `outreach/`, or existing `docs/` content was touched):

- **Program A (canonical substrate), `packages/canonical/`:** typed UUIDv7
  identifiers; explicit requested/negotiated/scheduled/predicted/actual time
  fields with a `known_as_of()` replay-cutoff method; a bitemporal-correction
  envelope; the 12 canonical entities from `docs/MASTER_ROADMAP.md`'s
  MilexiumDB table list (Tenant, ServiceRequest, Vehicle, Driver, Policy,
  ModelVersion, ForecastVintage, ScheduleRun, DecisionAlternative,
  DecisionEvent, Outcome, OutboxEntry); an 8-state ServiceRequest state
  machine; policy/reason-code/sensitivity vocabularies; an append-only,
  SHA-256 hash-chained decision-event log implemented *twice*
  (in-memory and SQLite-backed) against one shared contract; a portable SQL
  DDL file that runs unmodified on SQLite today and is intended for
  PostgreSQL later.
- **Program G (verify), `packages/verify/`:** independent JSON-Schema, state-
  transition, and hash-chain verifiers, deliberately organized as a separate
  package that never imports the event-log's write path — it re-derives
  legality and hash integrity from raw stored rows instead of trusting the
  writer's own bookkeeping.
- **SemanticIndex interface** (`packages/canonical/semantic_index.py`): a
  `Protocol` plus one reference implementation, brute-force cosine
  `ExactSearchIndex` — no TurboVec or pgvector adapter yet; vendoring TurboVec
  specifically requires a license/security review this session did not do
  (`architecture/decisions/0005-...md`).
- **Conformance suite:** 92 pytest tests across
  `conformance/fixtures/`, `conformance/property-tests/`, and
  `conformance/adversarial/` — exhaustive state-transition-table coverage (72
  parametrized cases), idempotent-command replay, duplicate-payload
  rejection, payload tampering detection, deleted-event gap detection,
  forged-hash chain-break detection, cross-tenant read isolation, and a
  database-level duplicate-sequence rejection test. All 92 pass;
  `tools/audit_repository.py` still passes unchanged (0 errors, 0 warnings).
- **ADRs 0001-0005** in `architecture/decisions/`: adopting the expansion
  blueprint; canonical schema technology (Pydantic v2 + generated JSON
  Schema); the append-only hash-chained event log design; SQLite-now/
  PostgreSQL-production storage strategy; the SemanticIndex interface
  decision.
- **`workstreams/DOSSIER_COVERAGE.md`:** seeded the full 80-technology/
  72-project ledger from the expansion's dossier, honestly marked
  Specified across the board (0/152 Exists) — Programs A and G now have a
  first versioned contract, which is not the same as any of the 152 specific
  technologies being implemented.
- **`IMPLEMENTATION_STATUS.md`:** the living Exists/Specified/Demonstrated/
  Validated/Production gap analysis this journal entry summarizes.

Deliberately not started this session: Programs B, D, E, F, H, I, J, K, L, M
(no code); real PostgreSQL wiring (engine installed, nothing talks to it);
PostGIS; object storage; TurboVec vendoring; any Lean/TLA+/SMT tooling.

Next planned tranche (pending checkpoint review with Arya): dispatch parallel
packets against the versioned A/G stubs — likely B (Connect adapter
skeleton), continued C (a Postgres-backed store implementing the same
`SqliteCanonicalStore` contract), and I (Evidence/Experience IR skeleton) —
each as a disjoint-path work packet in the `blueprint/19-agent-swarm-
execution-system.md` format.

## 2026-07-22 (website handoff and YC execution reset)

- Removed the tracked `web/` directory. Chris owns the new Milexium website,
  domain, and Cloudflare deployment outside this repository; keeping the old
  static site here created two sources of truth.
- Updated the repository map and structural audit so a website is no longer a
  required product-repository component. Curated product screenshots remain in
  `artifacts/demo-assets/` for demos and applications.
- Replaced the open-ended backlog with a deadline-gated execution plan through
  27 July 2026 at 8pm PT and added sourced competitive positioning. The technical
  wedge is now a decision-evidence system that sits alongside incumbent dispatch
  products, not an unsupported claim that Milexium already replaces them.

## 2026-07-22 (later): rebrand to Milexium

Company renamed TransitPulse -> Milexium. Tagline "Every mile, justified" proposed,
not yet confirmed. Chris is building the new marketing site at https://milexium.com
separately; `web/` in this repo (the old transitpulse-psi.vercel.app source) was
deliberately left untouched to avoid conflicting with that work. Updated company
name/URL/tagline references across active docs (README, MASTER_ROADMAP,
DATA_SOURCES, DATA_STORAGE, MODEL_CARDS, YC application draft), active scripts
(audit_repository.py, build_model_cards.py, fetch_osm_poi.py, make_real_demo_assets.py
x2, ntd/build_economics.py, ntd/fetch_ntd.py), and outreach/design_partner_pitch.md.
Left untouched on purpose: `docs/archive/` (historical record), prior JOURNAL.md
entries above this one (historical record), `artifacts/knowledge-graph/2026-07-21/`
(dated generated snapshot), and the live external resource identifiers `kaggle/transitpulse_transformer.ipynb`
and the Kaggle dataset `aryaarun07/transitpulse-real-panels` (renaming those means
recreating/re-pushing them on Kaggle - deferred, not blocking anything). Also
renamed the GitHub repo itself, aryaarun0910-debug/TransitPulse ->
aryaarun0910-debug/Milexium (`gh repo rename`), and updated the local `origin`
remote URL to match; GitHub redirects the old URL so existing clones (including
Chris's) keep working without action, though they should update their remote
URL when convenient. Local clone folder also renamed to `Milexium` to match.

## 2026-07-22: repository and data-storage audit

- Consolidated active planning into `docs/MASTER_ROADMAP.md`; moved superseded
  handoffs, initial plans, website briefs, and strategy notes to `docs/archive/`.
- Renamed the ambiguous synthetic `pipeline/` to `reference_agency/`. It remains
  the explicitly fictional trip-level source for scheduling demonstrations; real
  aggregate forecasting evidence remains in `realdata/`.
- Moved generated screenshots and the dated Graphify snapshot under `artifacts/`.
- Documented the 56 GB local data lifecycle in `docs/DATA_STORAGE.md` and added
  `tools/audit_repository.py` to check storage boundaries, schemas, duplicate
  keys, coverage, raw Parquet containers, checkpoint continuity, and links.
- The audit found a missing Chicago checkpoint for 2024-12 and empty header-only
  checkpoints incorrectly finalizing unpublished June/July 2026 data. Restored
  December, removed the false completions, rebuilt the panel, and increased the
  verified total to 555,422,454 trips through 2026-05. The fetchers now reject
  empty high-volume service days, distinguish `.partial.csv` current months, and
  publish checkpoints atomically through `.part` files.
- Final audit: all eight compact/local panels passed schemas and unique-key
  checks; all 88 FHVHV Parquet containers passed; monthly checkpoint sequences
  are continuous. The only warning is expected unfinished scope: green taxi has
  not been fetched.

## 2026-07-21 (evening): GPU acceleration, Kaggle live runs, nationwide data expansion

Discovered two capabilities that were sitting unused: (1) XGBoost GPU training works on this laptop's old MX350 (PyTorch's CUDA kernels don't support sm_61, but XGBoost's do), and (2) the Kaggle API is fully authenticated under account aryaarun07 with an existing token. Acted on both.

**GPU everywhere local:** switched all four real-data XGBoost models and the pretrain/finetune experiment to `device="cuda"`. Also added MTA bus (438 routes) and MTA subway (428 stations) models to train_real_models.py, so it now trains all four real modalities (AAR, Chicago, MTA bus, MTA subway) in one run.

**Kaggle live, not just a notebook to hand off:** uploaded the real panels as a Kaggle Dataset (aryaarun07/transitpulse-real-panels) and pushed the transformer notebook as an actual running kernel with `--accelerator NvidiaTeslaT4`. First run surfaced two real bugs the local CPU smoke test could not: (a) Kaggle silently decompresses uploaded .csv.gz to .csv, so every attached panel lookup failed (fixed with a find_panel helper checking both suffixes); (b) TEST_MODE's 6-month window couldn't fit the 90+90-day tune/test reservation, leaving zero training windows (fixed by scaling TUNE_DAYS/TEST_DAYS down under TEST_MODE). The first completed run gave an honest bad number: pretrain on TLC-alone got R2 -0.56 vs naive 0.91 on the untouched test set. That is a confounded, incomplete run (TLC-only, no multi-city pretrain, no AAR finetune, all because of the .gz bug), not a fair test of the design - re-running with the fix. Whatever the corrected number is, it ships next to the naive baseline, win or lose.

**Nationwide data expansion (the "more data than people can get" push, all resumable through a laptop shutdown):**
- NTD Monthly nationwide demand-response panel: 637 agencies, 2002-2026, 2.18 BILLION paratransit trips (realdata/panels/ntd_monthly_dr.csv.gz, ~2 MB gzipped, committed). This is the broadest public paratransit demand data that exists - every reporting US agency's monthly ridership time series. Complements AAR's hourly single-agency depth with national breadth. Not yet modeled.
- NYC TLC Yellow + Green taxi download (realdata/fetch_tlc_yellow_green.py, raw_tlc_taxi/ gitignored): 2011-present, 15+ years, two more real NYC demand modalities. Running at shutdown; resume by rerunning the script (skips existing files).
- NOAA NCEI HOURLY weather for NYC + Chicago (realdata/fetch_weather_hourly.py): upgrades the daily weather feature to hourly. Uses the token-free bulk LCD CSVs; a CDO token is saved in .env for any future API use.

**Honest scope note:** true trip/stop-level APC data is NOT public - agencies hold it. There is no download for it; it becomes accessible through a pilot. The nationwide NTD monthly panel is the closest public equivalent and is now captured. Did not launch low-value downloads (GTFS schedules, tract census) just to fill the window.

**Resume after shutdown (all resumable, rerun from repo root):**
```
py -3 realdata/fetch_tlc_yellow_green.py   # continues taxi download
py -3 realdata/fetch_weather_hourly.py     # re-fetches hourly weather (one-shot, fast)
py -3 realdata/train_real_models.py        # GPU, all 4 models -> metrics_real.json
py -3 realdata/pretrain_finetune_xgboost.py # GPU transfer-learning experiment
```
Kaggle transformer: check https://www.kaggle.com/code/aryaarun07/transitpulse-transformer-test-mode; when the TEST_MODE run is validated, flip TEST_MODE=False and push the full-scale run. Optional WMATA key still pending from Arya for DC ridership.

## 2026-07-21 (later): code review found real bugs, all fixed and verified

An external review of commit 14dd8b9 (the one pushed for Codex to look at) found six real issues, five of them substantive enough to actually change numbers or claims. All verified against the code before fixing (not taken on faith), then fixed, then re-verified. This entry is the record of what was wrong and what changed.

**P1, fixed: silent-failure fetchers marking incomplete months as done.** `fetch_mta_apc.py` and `fetch_chicago_panel.py` retried a failed day 5 times, then returned an EMPTY DataFrame instead of a failure signal; the caller concatenated that empty result into the month and wrote it to disk unconditionally, so the `if dest.exists(): continue` resume check treated a month with silently-missing days as permanently complete. Fixed: `fetch_day` now returns `None` on failure (never indistinguishable from a legitimately-empty response), and a month is only written if every one of its days succeeded — otherwise the whole month is left unwritten so the next run retries it in full. Audited every already-downloaded month file for gaps before trusting any of them further: found exactly one casualty, `mta_bus_monthly/2026-07.csv` (missing days 15-18 within its own expected range), deleted it, let the fixed fetcher redo it. Everything else scanned clean.

**P1, fixed: transformer notebook reused the holdout for both checkpoint selection and reported metrics.** Both training stages picked the best epoch using `valid_dl`, then reported final numbers on that same loader — that's tuning-set performance, not holdout performance. Fixed: real three-way split, `train` / `tune` (checkpoint selection only) / `test` (final holdout, touched exactly once, at the very end of each stage). Verified this doesn't just move the goalposts by re-reading every cell that touches `test_dl`/`ft_test_dl` to confirm nothing upstream of the final evaluation cells ever sees those pairs.

**P1, fixed: shared-clock densification fabricated zero demand.** `build_matrix()` spanned the earliest-to-latest date across ALL attached datasets and zero-filled every entity for the full range — so an entity from a dataset that starts later than another attached dataset (MTA bus from 2020-01 while TLC runs from 2019-02) got FABRICATED zero-demand training examples for the gap, not correct exclusion. Fixed: track each entity's real coverage (first/last hour actually observed, computed before zero-filling) and only build train/tune/test windows that fall entirely inside it. Verified the fix logic locally with a synthetic two-dataset test before touching the notebook — confirmed the old approach would have produced 40 fabricated-zero windows for a late-starting entity and the fixed approach produces zero.

Discovered mid-fix that this laptop actually has PyTorch installed (2.10.0+cu128) and a GPU (an old NVIDIA MX350, too weak and too old an architecture for this PyTorch build's compiled kernels to actually use, but CPU execution works fine). Used that to go one step further than pandas-only verification: wrote a standalone CPU smoke test reproducing the exact architecture, window-construction, and training loop from the notebook against tiny synthetic data, and ran it. Forward pass, backward pass, loss computation, the tune/test split, and the non-crossing-quantile constraint all passed. This is not the same claim as "the real GPU run happened" — it is the claim that the code itself runs correctly, which is a real, if partial, upgrade from pure static review.

**P1, fixed: ACS latent-demand data mislabeled as ADA-eligible population.** docs/DATA_SOURCES.md and the fetch script's docstring said residents are "ADA-paratransit-eligible by age/disability alone." This is legally wrong: 49 CFR Part 37 Subpart F defines paratransit eligibility by FUNCTIONAL inability to use fixed-route service (often trip-specific), not by age or disability status alone — age in particular does not qualify anyone. This was a real credibility/legal-accuracy risk if it had ended up verbatim in outreach to a compliance officer who knows the regulation. Fixed everywhere: reframed as a latent-mobility-need proxy for market sizing, never an eligibility count.

**P2, fixed: conformal calibration set was also used for XGBoost early stopping.** `train_real_models.py` fit with `eval_set=[(cal, cal.y)]` for early stopping, then used that same `cal` block's residuals to calibrate conformal intervals — using one block for both purposes forfeits the clean split-conformal exchangeability guarantee. Fixed: real four-way split, train / tune (early stopping only) / cal (calibration only, never seen during fit) / valid (final reporting). Retrained AAR after the fix: R2 0.985 vs 0.923 naive (was 0.987 pre-fix) — materially unchanged, which is reassuring: the original result wasn't an artifact of the conflation, it just hadn't been rigorously isolated from it.

**P2, fixed: notebook claimed weather sensitivity but never loaded weather; parameter count was wrong; notebook status wasn't documented.** The intro claimed the model learns "weather sensitivity," and kaggle/README.md said `weather_daily.csv` should be attached, but no cell ever read or used it — the model only ever saw log-count and calendar features. Fixed: weather is now a real 4-channel input (tmax/tmin/precip/snow, city-indexed per dataset, zero-filled and skipped gracefully if not attached). Separately, kaggle/README.md claimed "roughly 15-20M parameters" without ever computing it; the true figure, verified analytically against PyTorch's documented layer shapes (not guessed, not run — I don't have a GPU to execute the notebook), is 4.92M to 5.15M depending on how many datasets are attached. Also added an explicit "this notebook has not been executed end to end" notice to both the notebook and its README, since it hadn't been and the earlier version didn't say so.

**P2, fixed: "APC-sourced" MTA bus data was inaccurate.** MTA's hourly bus and subway ridership datasets are OMNY/MetroCard fare-payment (AFC) derived, not onboard-sensor (APC) data. Real, legitimate ridership proxy either way, but conflating the two terms is the kind of thing a transit-industry-literate reader (an FTA person, an actual paratransit ops director) would catch immediately, undermining the domain-credibility claim we're actually going for. Fixed the terminology everywhere (docs/DATA_SOURCES.md, realdata/README.md, docs/JOURNAL.md, the fetch script's own docstring), without renaming the script itself.

**Separately, in response to a large "enterprise product/architecture" brief Arya pasted mid-session:** triaged rather than executed wholesale. The brief's own closing section ("Do Not Build For Appearances") argues against most of itself for a two-founder pre-launch repo four days from a deadline — building OR-Tools VRPTW, a dispatcher console, Temporal/Dagster/MLflow infra, or SOC2/HIPAA compliance apparatus this week would look less credible, not more. Kept: the reframing of the audit trail as "compliance-grade replay" (deterministic, rule-traceable scheduling decisions, never SHAP — SHAP stays scoped to demand-forecast explanation only, which the existing scheduler already does correctly, just not documented as a deliberate separation), and the correction that AAR is aggregate borough-hourly data, useful for validating demand FORECASTING but not individual-trip DISPATCH decisions. Everything else from that brief is logged as future-scope, not built.

Every fix above was verified against the actual code before changing anything (grepped for the exact claims, read the exact functions) and re-verified after (retrained models, compile-checked every touched script, ran the coverage-masking logic against synthetic data). Nothing in this entry is taken on the reviewer's word alone.

## 2026-07-21: rigor pass, real AFC ridership data, monolith transformer redesign, knowledge graph

Directive this session: outreach deferred to later today, full focus on model/data/technical sophistication. Arya confirmed all four positioning ideas from yesterday's discussion (audit-trail-as-product, self-serve calculator, regulatory tailwind, technical depth as credibility signal) and asked for the repo to be structured like a lab notebook. Also: AI attribution is fine going forward (see [[arya-style-rules]]), travel meant the laptop closed mid-session; both long downloads are written to resume cleanly (see below).

### Hygiene: killed a data-corruption bug before it mattered

Two background fetches from the prior session survived the laptop shutdown as orphaned OS processes (Windows does not reliably kill children when the harness's tracking says "stopped"). They raced the freshly-resumed fetchers on identical output filenames, producing `WinError 32` file-lock errors and at least two possibly-corrupted `.part` files. Found via `Get-CimInstance Win32_Process -Filter "Name='python.exe'"` cross-referenced against command lines, killed the stale PIDs, deleted the two suspect partials, let the live processes redownload them clean. Lesson: after any laptop sleep/close during a background fetch, check for duplicate processes before trusting "resumed" output.

### Real AFC-sourced ridership: MTA bus and subway (realdata/fetch_mta_apc.py)

Added MTA Bus Hourly Ridership (447M+ raw rows, 2020-present) and MTA Subway Hourly Ridership (121M+ raw rows, 2020-present), both real fare-tap (AFC, OMNY/MetroCard) derived ridership by route/station and hour. Correction (see the 2026-07-21 review-fixes entry below): this is fare-payment data, not onboard-sensor APC data, and earlier notes in this journal and in DATA_SOURCES.md calling it "APC-sourced" were wrong; fixed throughout. This is the phase-2 (fixed-route/campus/hub) evidence base and, combined with Chicago TNP and NYC TLC, the pretraining corpus for the transformer. Chicago's day-chunked fetcher (from the 20 July session) was found to be dangerously slow on the older 2018-2022 dataset (~50s/day sequential, projecting 20+ hours) and was rewritten to fetch days concurrently (ThreadPoolExecutor, 4 workers) with soft-fail-and-gap-log instead of a hard crash on a bad day.

### Rigor: walk-forward backtest and SHAP explainability on the real AAR model (realdata/backtest_and_explain.py)

Replaced the single 90-day holdout with a 4-fold rolling-origin backtest (expanding training window, non-overlapping 90-day folds walking back to mid-2025). Result: model R2 0.972 mean (std 0.023) vs naive 0.919 mean (std 0.025) across all four folds, including a materially harder winter fold (0.934 vs 0.878) — a single lucky holdout window was a weak claim; four consistent folds is a strong one. Also ran SHAP TreeExplainer on the production model: lag7 (same day last week) dominates global importance (0.70 mean |SHAP|), followed by lag14 and the 28-day rolling mean; six worked "why this forecast" examples generated from the real model on real data, in the same plain-language format the product's explanation cards use (realdata/explanations_aar.json). Refined the conformal intervals to test hour-of-day-bucket conditioning (conformal_two_way in train_real_models.py) against the original prediction-decile-only version: result was a wash (97.8% vs 98.1% coverage, near-identical width), an honest negative finding worth keeping — it means the point prediction already encodes most of the hour-driven variance, so conditioning on hour again added nothing. Both methods are reported in metrics_real.json.

### Self-serve savings calculator (ntd/savings_calculator.py)

Built the backend for the "punch in your agency, see your own numbers" website widget Arya and Chris agreed on: public-data-only (every figure from the agency's own NTD filing), zero PHI, zero routing demo, so it doesn't touch the locked no-public-map-demo rule. Fuzzy agency search plus a computed savings scenario (deadhead-cut dollar value where deadhead data exists, cost-per-trip-gap-vs-median otherwise, honest "you already run lean" message when neither applies). Deliberately built ahead of the website (which stays last) because it's pure computation reusing data already on hand.

### Monolith transformer redesign: pretrain-then-finetune (kaggle/transitpulse_transformer.ipynb)

Arya asked directly why not train one big neural net across everything, given a 12-hour Kaggle T4 budget. Decision: not a flat single-loss mashup — the ~1.7B-trip mass-transit corpus would drown the ~93k-row AAR paratransit target in any joint loss. Redesigned as two stages: Stage 1 pretrains one shared transformer (d_model 256, 8 heads, 6 layers, ~15-20M params, dual Poisson-mean + quantile-pinball heads for native uncertainty) on the combined real mass-transit corpora (TLC always, Chicago/MTA bus/MTA subway if attached as an optional Kaggle Dataset), using a (dataset, zone) entity embedding so cities don't collide. Stage 2 fine-tunes on AAR specifically: new borough and dataset embeddings at full learning rate, pretrained backbone at 5% of that rate. This is a genuine transfer-learning claim for the application, not a parameter-count flex, and the notebook is explicit that the finetuned result must be compared against the XGBoost result in realdata/metrics_real.json before claiming the transformer is better.

### Data catalog and knowledge graph

Added docs/DATA_SOURCES.md: single-page index of every dataset (source, volume, dates, license, repo location, fetch script), including a section on sources investigated and rejected (London Dial-a-Ride: real UK paratransit-equivalent, but quarterly/local-authority granularity and over a decade stale — not usable, logged so no future session re-investigates it). Also ran /graphify on the full repo with Obsidian output to C:\Users\aryaa\Documents\Obsidian\GraphifyVault, per Arya's request to make the project queryable like a second brain across sessions.

### Product positioning, confirmed (not yet built into the application draft)

Four ideas from the prior session's "how do we sell this without outreach" discussion, all confirmed by Arya: (1) position the audit trail as the product — "every denial, litigation-ready, in one click" — not a feature bolted onto a routing algorithm; (2) the savings calculator above as the zero-call-required "wow"; (3) algorithmic-accountability regulatory tailwind as the "why now" (checked: S.2164, the Algorithmic Accountability Act of 2025, is real and pending in Senate Commerce Committee as of mid-2026, no paratransit-specific language yet, so cite it as a directional signal, not a settled mandate); (4) technical depth (walk-forward validation, honest baselines, calibrated uncertainty, billion-scale real data) as the credibility substitute for traction. None of this is written into docs/yc-application-draft.md yet — that file still does not exist.

### Running or interrupted at end of session

Background at last check: MTA bus hourly fetch ~56/78 months done; MTA subway hourly not yet started (queued after bus completes in the same process); Chicago TNP panel restarted with concurrent fetching, early days in progress. TLC parquet is fully complete (39.8 GB, Feb 2019 to May 2026, one gap patched). Resume commands, all skip-if-exists:

```
py -3 realdata/fetch_mta_apc.py          # bus then subway, resumes mid-feed
py -3 realdata/fetch_chicago_panel.py    # concurrent day-chunked, resumes mid-month
```

Then, once panels exist: `py -3 realdata/train_real_models.py` (adds Chicago), `py -3 realdata/aggregate_tlc.py` (TLC parquet -> zone-hour panel for local use), and re-run `py -3 realdata/backtest_and_explain.py` for Chicago's walk-forward + SHAP once its model exists.

## 2026-07-20 (evening): real data replaces guesswork

Directive shift from Arya this session: maximum scale ("a year of founder output per day"), real data over synthetic, transformer-scale training on Kaggle GPUs, retire the synthetic pipeline once real data fully covers it, keep the repo organized and journaled, website deliberately last. AI attribution on commits is now fine (rule reversed by Arya; no-emoji and no-em-dash rules stand).

### NTD: the entire US demand-response market, quantified (ntd/)

- Pulled FTA National Transit Database metrics and service tables (modes DR and DT, 2022-2024) from data.transportation.gov: 6,108 agency-mode-year rows, 3,075 agencies.
- Built agency_economics.csv: per-agency trips, opex, cost/trip, revenue hours, deadhead share, ADA share, and the dollar value of a 10 percent deadhead cut computed from each agency's own filing.
- Market sizing (2024 report year): 1,920 agencies, 139.7M annual trips, $7.06B operating expense, median $37.97 per trip, expense-weighted deadhead 17.3 percent of vehicle hours, $94M/year value in a 10 percent deadhead cut across the 413 full reporters.
- Sanity checks passed against known reality: LA Access Services 4.2M trips at $59, NYC AAR $96, WMATA $135 per trip.
- Generated outreach/targets_ntd.csv: 80 tiered targets (A: 50k-1M trips, B: 20k-50k, C: over 1M), each with a personalized hook sentence from its own NTD numbers.

### Real demand data and models (realdata/)

- NYC Access-A-Ride: 26.3M real paratransit bookings, hourly by borough and provider type, Jan 2024 to May 2026 (panels/aar_hourly_borough.csv.gz) plus the daily series from Mar 2020 (panels/aar_daily.csv). This is our exact target variable from the largest US paratransit operation.
- Weather: Open-Meteo daily history for Chicago and NYC since Nov 2018 (panels/weather_daily.csv).
- Trained the borough-hour AAR model, protocol identical to the synthetic pipeline: strict temporal split (last 90 days validation, prior 90 calibration), XGBoost count:poisson, seasonal-naive baseline, split-conformal intervals.
- Headline result on REAL paratransit demand: R2 0.987 vs 0.923 naive, MAE 19.7 vs 55.5 (64 percent error reduction), conformal coverage 98.1 percent at a 90 percent target (conservative; calibration window straddled winter). Full numbers in realdata/metrics_real.json.
- Honest finding kept on purpose: without demand-history lag features, calendar+weather ties the naive baseline (R2 0.919 vs 0.921). The lags (1/7/14-day and trailing 28-day mean, all available day-ahead) are what beat climatology.
- Chicago TNP: month-level server-side group-bys time out on the 200M-row 2018-2022 dataset, so the fetcher was rewritten to day-level chunks with per-month files and skip-if-exists resume (fetch_chicago_panel.py). It was running when this session ended.
- NYC TLC FHVHV bulk download (fetch_tlc_parquet.py): monthly parquet, about 40 GB total for 2019-2026, resumable; 19 files (7.9 GB) landed before this session ended. aggregate_tlc.py (DuckDB, out-of-core) turns whatever is on disk into a zone-hour panel.

### Kaggle GPU track (kaggle/)

- transitpulse_transformer.ipynb: complete notebook that downloads the TLC corpus inside Kaggle, aggregates with DuckDB, and trains a ~1M-parameter temporal transformer (336h context, 24h horizon, Poisson NLL, zone embeddings) with the same holdout-plus-naive-baseline protocol. TEST_MODE flag for a 20-minute smoke run. Arya runs this on Kaggle (GPU on, internet on).

### Plan and docs

- docs/yc-plan-jul25.md rewritten from day-by-day schedule to a living execution backlog (Arya: no dates, we outrun any schedule; add tasks as they appear).
- docs/HANDOFF.md attribution rule updated.
- READMEs added: ntd/, realdata/, kaggle/; root README structure updated.

### Running or interrupted (laptop travels, both fetchers are resumable)

Resume with exactly these two commands from the repo root; each skips everything already on disk:

```
py -3 realdata/fetch_chicago_panel.py   # day-chunked, writes panels/chicago_monthly/
py -3 realdata/fetch_tlc_parquet.py     # writes raw_tlc/*.parquet (gitignored)
```

Then, when panels exist:

```
py -3 realdata/train_real_models.py     # adds the Chicago model to metrics_real.json
py -3 realdata/aggregate_tlc.py         # TLC parquet -> zone-hour panel
```

### Decisions this session

- Scale tooling: DuckDB and PyArrow (C++/Rust engines) over a new language; Kaggle GPUs for anything needing CUDA. Revisit only if profiling shows a real bottleneck.
- "APC data" for paratransit does not exist publicly; the real equivalents chosen: AAR hourly (actual paratransit), Chicago TNP and NYC TLC (door-to-door demand at scale), MTA hourly station ridership (optional APC-style corpus, not yet pulled).
- Synthetic pipeline stays until (a) real-data demo assets exist and (b) the audit-trail scheduler has a real booking stream (Chicago TNP trip records are the candidate). Then it gets retired per Arya's directive.

## 2026-07-20 (daytime, prior session): foundation

Repo refocused on TransitPulse (paratransit positioning, two founders, YC 25 July plan, website brief for Chris). v1 synthetic pipeline built and committed: trip generator anchored to NTD norms (about 90k bookings, 245/day), zone-hour XGBoost demand model (R2 0.839 vs 0.817 naive, 90-day temporal holdout), audit-trail scheduler (229/253 placed, 77 percent pooled, deadhead 17 percent, every decision and denial logged with factors and rejected alternatives), five rendered demo PNGs in docs/demo-assets/. Handoff written to docs/HANDOFF.md.
