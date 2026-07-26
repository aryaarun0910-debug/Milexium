# app/

Implementation packages, one per program from `SWARM_MANIFEST.yaml` in the
expansion plan. Each package owns a disjoint path; cross-package contract
changes require an ADR in `forge/knowledge/architecture/decisions/` first.

**Polyglot note (ADR-0026):** most of `app/` is Python. Two non-Python
homes now exist: `argus/sdk-typescript/` (`@milexium/sdk`, generated from the
OpenAPI contract — ADR-0029) and the Rust workspace at `forge/legacy/crates/` (the
evidence-verifier crate, differential-tested against Python — ADR-0028). The
`talos/contracts/` layer is the language-neutral source; Python remains first-class
and the reference implementation.

| Package | Program | Status |
|---|---|---|
| `canonical/` | A — canonical transport substrate | v0.1 Exists: entities, ids, time, state machine, vocab, event log (in-memory + SQLite), SemanticIndex interface, a PostgreSQL-backed store (`postgres_storage.py`), and (new) a **request-independent operational entity family** — `VehicleObservation`/`StopTimeObservation` with a **PostGIS** geometry column kept out of the portable base DDL (`sql/postgis_postgres.sql`, `observation_store.py`), closing the ADR-0031 gap — see ADR-0035 |
| `verify/` | G — independent verifiers | v0.1 Exists: schema, state-transition, hash-chain verifiers, plus (new) **machine-checked formal invariants** — `formal.py` runs z3/SMT proofs in `forge/knowledge/architecture/formal/` (state-machine safety S1–S4 + hash-chain tamper-evidence H1) and ties them to the real contract with a consistency check — see ADR-0033 |
| `connect/` | B — Milexium Connect | Exists: generic adapter contract plus **five** adapters — `reference_agency` (fictional CSV), NYC TLC (real Parquet), **TIDES**, **GTFS-Flex** (all → `ServiceRequest`), and **GTFS-Realtime**, now re-mapped onto the operational entities (→ `VehicleObservation`/`StopTimeObservation`; real MBTA/Google samples): the synthetic-`request_id` squash ADR-0031 recorded is gone (MBTA 567/567 mapped, 0 quarantined). TODS/NeTEx still Specified — see ADR-0007, 0011, 0014, 0031, 0035 |
| `sdk/` | M — APIs/SDK/ecosystem | v0.1 Exists: `MilexiumClient` facade — one import drives the whole loop (in-memory setup → ingest → record decision/override → verified evidence packet); runnable ten-minute quickstart. HTTP/CLI/plugin-cert/TS+Rust SDKs Specified — see ADR-0015 |
| `evidence/` | I — Evidence/Experience IR | v0.2 Exists (teardown re-derivation ADR-0044; **redaction fixed** ADR-0045): `EvidencePacket`/`ExperiencePacket` + independent hash-chain/schema verification, and a portable **evidence-pack export** (`build_evidence_pack`/`verify_evidence_pack`/`redact_pack`) a third party can re-verify without Milexium — see ADR-0009, 0012, 0017 |
| `core/` | D — Core/adaptive memory | v0.3 Exists (**persistent**, ADR-0041): task/model registry (`ModelRegistry`, closed `TASK_REGISTRY`) cataloging this repo's 5 real trained models, plus (new) the **adaptive-memory slice** — a leakage-safe point-in-time `FeatureStore` (strict past-only as-of reads, proved by future-corruption on a real panel), a champion/challenger/canary `PromotionController` with an evaluated gate + recorded rollback, and a `drift` service (PSI/KS/CUSUM). Memory tiers + parameter-delta registry still Specified — see ADR-0010, 0034 |
| `estate/` | C — data-estate layer | v0.1 Exists: manifest-gated acquisition (`AcquisitionManifest`, `acquire()` with free-space guard + quarantine + checksum + content-addressed promotion) and catalog inventory/free-space reporting; the raw zone is now additively **backed by MinIO** (content-addressed, key == sha256, local disk still default) — see ADR-0013, 0032, 0036 |
| `forecast/` | E — Forecast runtime | v0.2 Exists: `ForecastRuntime` serves a `ForecastVintage` from any of the **four** real registered models (AAR/Chicago/MTA bus/subway), hash-verifying the artifact, with **serve-time split-conformal prediction intervals** (`conformal.py`) — see ADR-0016, 0030 |
| `decide/` | F — Decide/optimization | v0.1 Exists: Decision IR + grid-exact solver + **independent** feasibility checker (one-way solver→checker dep). v0.2 adds a scalable routing DARP solver (regret insertion + LNS) benchmarked on published Cordeau instances — reached a proven optimum (`aletheia/benchmarks/quality/`). Additive, not the founder-owned scheduler — see ADR-0022, 0024 |
| `replay/` | H — Replay/comparison | v0.2 Exists (+ **deadhead teardown**, ADR-0039): info-cutoff-safe historical replay + baseline-vs-Milexium metric comparison, worded as a modelled comparison (not causal proof) — see ADR-0019 |
| `api/` | M — HTTP surface | v0.2 Exists (+ `POST /teardowns`, `POST /operator-exports/validate`, ADR-0042): FastAPI app mirroring the SDK loop with an auto-generated OpenAPI contract at `/openapi.json` — see ADR-0021 |
| `explain/`, `forge/`, `fabric/`, `runtime/`, `edge/` | J, K, L | Not created yet — created when their upstream dependency has a versioned stub, per the dependency rules in `blueprint/19-agent-swarm-execution-system.md` |

Also present: `estate/` (Program C data-estate layer — see above). Program C
also now enforces **PostgreSQL row-level security** for tenant isolation
(`themis/canonical/sql/rls_postgres.sql`, ADR-0018), and Program I gained
**period/incident/procurement evidence bundles** (`aletheia/evidence/packs.py`,
ADR-0020).

**Owner:** whoever owns the corresponding workstream packet in `forge/knowledge/workstreams/`.

**Version policy:** a package's public interface is whatever it exports from
its top-level module; that surface follows the same immutable-contract rule as
`forge/knowledge/architecture/contracts/`.

**Test command:** `py -3 -m pytest app/<name>/` once a package has tests.
