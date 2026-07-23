# benchmarks/

Measured, reproducible performance and quality evidence — not aspirational
targets. A number only belongs here once it was actually measured on this
repository's code, with the command that produced it recorded alongside.

- **`quality/`** — forecast/solver/retrieval quality vs. declared baselines.
- **`systems/`** — latency, memory, and throughput benchmarks.
- **`cost/`** — token, compute, and storage cost benchmarks.

**Owner:** the package owner producing the benchmark; the reliability/adversarial
workstream may add regression benchmarks independently.

**Version policy:** each benchmark result records the code commit, data/fixture
version, and hardware it ran on. Results are appended, not overwritten, so
regressions are visible in history.

**Test command:** `py -3 -m pytest benchmarks/ -m benchmark` (once benchmarks
exist — this directory is scaffolding only as of the expansion kickoff).
