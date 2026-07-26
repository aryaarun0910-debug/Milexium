# evidence/conformance/

Executable proof that an implementation matches its normative contract in
`knowledge/architecture/contracts/`. This is what the expansion plan's "Demonstrated" and
"Validated" status labels must point to as evidence — a claim without a passing
fixture here stays "Specified."

- **`fixtures/`** — example canonical records, transitions, and corrections used
  as golden inputs across every implementation of a given contract.
- **`goldens/`** — recorded expected outputs (hashes, serialized states) that a
  new implementation must reproduce exactly, or explain a version bump.
- **`property-tests/`** — property/metamorphic tests (e.g. "every valid state
  transition sequence produces a verifiable hash chain").
- **`adversarial/`** — malformed input, tenant-crossing, and race-condition
  fixtures owned jointly with the reliability/adversarial workstream.

**Owner:** shared between the package owner and the reliability/adversarial
workstream; neither may weaken a fixture to make their own implementation pass
without an ADR.

**Version policy:** fixtures are versioned alongside the contract they test.

**Test command:** `py -3 -m pytest evidence/conformance/`
