# ADR-0026: Polyglot strategy and language ownership (adopted, phased)

- **Status:** Accepted
- **Date:** 2026-07-24

## Context

Chris proposed evolving Milexium from a predominantly-Python codebase into a
three-language platform: **Rust** for the performance-sensitive, verifiable
data plane; **TypeScript** for the control plane / SDKs / API composition;
**Python** for model research, training, and specialist workers — with one
authoritative contract layer generating clients for all three, and a full
service decomposition (gRPC mesh, Temporal, object storage, streaming, Docker,
cross-language CI).

The destination architecture is sound and is close to how a mature transport-
intelligence platform should be built. The open question was **not "polyglot
yes/no" but "how much, now."** The current Python stack works, is tested (455
passing tests), demonstrably runs the whole loop on real public data (Phase 1
+ 2), and has no measured bottleneck. The company is pre-traction with a YC
target and a two-person team.

## Decision

**Adopt the polyglot destination, sequence it, and start contracts-first.** The
language ownership model is accepted as the target:

- **Rust** — canonical types/validation, state-machine + bitemporal processing,
  ingestion/reconciliation, Arrow/Parquet, object storage, point-in-time
  features, **independent decision/feasibility/evidence verification**, semantic
  index kernels, replay reconstruction, streaming workers, CPU/GPU kernels,
  edge/offline runtimes, security-sensitive parsers.
- **TypeScript** — API gateway/composition, auth/session, workflow
  orchestration, job coordination, experiment/promotion control, operator
  approval/override, admin APIs, the developer SDK and generated clients, the
  Forge control plane.
- **Python** — notebooks, public-data analysis, feature/statistical/ML/Bayesian/
  survival/graph/spectral research, conformal calibration, causal/uplift,
  simulation calibration, autonomous research, model packaging, specialist
  solver adapters where the upstream ecosystem is Python/C++.

Python remains a **first-class scientific environment** and the reference
implementation; it is no longer the mandatory execution path for every
production operation *as capabilities migrate*.

### What is implemented NOW (this ADR's tranche) — cheap, reversible, strategy-advancing

1. A `talos/contracts/` layer generated from the Python source of truth (JSON Schema +
   OpenAPI today; Protobuf/Buf codegen seeded and deferred — ADR-0027).
2. A **Rust workspace + one proof crate: the evidence hash-chain verifier**,
   differential-tested byte-for-byte against the Python verifier. Chosen first
   because verifiability is the moat: "an independent Rust verifier that agrees
   with the Python one on every clean and tampered chain" is a checkable
   credibility artifact, not a speculative rewrite.
3. A **TypeScript SDK generated from the OpenAPI contract** — the one polyglot
   piece with immediate integration value (JS shops can integrate).
4. **Docker Compose + GitHub Actions CI** foundation (both in Chris's brief and
   independently worth doing now).

### What is DEFERRED (recorded so the record is complete, not rejected)

Per the migration discipline in Chris's brief itself ("do not perform a blind
rewrite… preserve current behavior"), these wait for a real trigger — a user, a
**measured** bottleneck, or a second engineer to own Rust — rather than being
built before demand (`blueprint/15` risk #1, "infrastructure before demand"):

- Rewriting ingestion / canonical state / decision as Rust services.
- The 9-service gRPC decomposition and inter-service mesh.
- Temporal durable workflows; Kafka/Redpanda streaming.
- ONNX/portable Rust inference for models.
- The full object-storage-backed data plane (MinIO is in the compose file for
  dev; production wiring follows a pilot).

Each deferred item gets its own ADR when its trigger fires, following the
brief's migration ladder: freeze behavior with golden/property tests → define
the contract → implement the Rust/TS replacement → **differential-test against
Python** → benchmark → route a challenger path → keep rollback → promote only
on demonstrated parity + improvement → retain Python as reference.

## Consequences

- The architecture is now genuinely polyglot-capable (Rust + Node toolchains
  present; contracts generated) without the runway cost of a full rewrite.
- Every migration is gated by differential parity against the Python reference —
  the same generator/verifier-separation discipline the codebase already uses.
- No existing command breaks: Python `pytest`/`audit`/`demo` all still run; Rust
  and TS are additive workspaces.
- This ADR is the anchor; ADR-0027 (talos/contracts/codegen), 0028 (Rust verifier
  parity), 0029 (TS SDK), and the infra decisions are its children.
- If a measured bottleneck or a real integration need appears, the deferred
  list is the pre-agreed next step — the decision is already reasoned, only the
  trigger is pending.
