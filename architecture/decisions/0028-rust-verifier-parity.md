# ADR-0028: Rust evidence-verifier crate with byte-for-byte Python parity

- **Status:** Accepted
- **Date:** 2026-07-24

## Context

The first Rust crate (ADR-0026) proves the polyglot pattern on the highest-value
target: the evidence hash-chain verifier. Verifiability is Milexium's moat, so
"an independent Rust verifier that agrees with the Python reference on every
chain" is a checkable credibility artifact. The requirement was **byte-for-byte
parity** with `packages/verify/hash_chain_verifier.py` and
`packages/canonical/events.py` — a Rust reimplementation that disagreed on any
input would be worse than none.

## Decision

`crates/verifier/` (a Rust workspace at the repo root, `resolver = "2"`, one
crate now, modular for future siblings) reimplements `canonical_json`,
`compute_hash`, and `verify_chain` in Rust (deps: `sha2`, `serde`, `serde_json`;
hex hand-rolled). A binary reads raw rows from stdin and emits violations as
JSON. Parity is enforced by a Python **differential** test
(`conformance/property-tests/test_rust_verifier_parity.py`) that runs both
implementations on the same fixtures and asserts identical violation tuples.

Parity specifics that had to be exact:

- **`canonical_json` is hand-written**, not `serde_json::to_string`: parse
  `payload_json` → `Value`, re-serialize with sorted keys and compact `,`/`:`
  separators — matching Python's `verify_chain`, which itself does
  `json.loads` then re-serializes. Parse→canonical-serialize round-trip is what
  is matched, not the stored bytes.
- **`ensure_ascii` fully replicated** (not an ASCII-only shortcut): reproduces
  CPython's `c_encode_basestring_ascii` — the five short escapes, and `\uXXXX`
  for every control char / `0x7f` / non-ASCII, with astral code points split
  into a UTF-16 surrogate pair. Proven: a payload `"café 🚌 Ω"` (🚌 = U+1F68C →
  `🚌`) produces identical recomputed hashes, which is only possible
  if the canonical JSON bytes are identical.
- **Violation `detail` strings byte-identical**, including Python's `!r` repr
  for `prev_hash_mismatch`.

The Rust and Python verifiers were confirmed to produce identical violation sets
on: clean, clean-non-ASCII, payload-tamper, deleted-middle-gap,
forged-hash-chain-break, and a mixed multi-aggregate tenant.

## Honest limitation (recorded, not hidden)

Not covered by tests: **exotic float formatting** (huge exponents like `1e300`,
`-0.0`) could diverge from CPython's `repr(float)`, and `py_repr` for the
`prev_hash_mismatch` detail doesn't fully replicate CPython's `unicodedata`
repr for arbitrary exotic-Unicode strings. Neither occurs in the domain — event
payloads are integers/strings/bools/null/nested objects (no floats), and
`prev_hash` is only `None` or 64-char hex — so this is outside the tested
surface, not a hidden bug. If float payloads ever enter, the parity contract
must be extended and re-tested first.

## Consequences

- Milexium's core verifier now has **two independent implementations that agree
  byte-for-byte** — a genuine, checkable strengthening of the verifiability
  moat, and a working proof that the polyglot migration ladder (differential-
  test against Python) is real.
- The Python verifier remains the reference; the Rust crate is additive. CI
  runs `cargo fmt`/`clippy -D warnings`/`test`, and the differential test skips
  cleanly where `cargo` is absent so the Python suite stays green on any runner.
- Pattern established for the deferred Rust data-plane work (ADR-0026): each
  future crate ships with a differential parity test against its Python
  reference before it can be trusted.
