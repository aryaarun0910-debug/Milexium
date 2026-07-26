# ADR-0071: A test that could not fail, and a null result that could not be reproduced

- **Status:** Accepted
- **Date:** 2026-07-26
- **Packet:** MX-CONF-GOVERNANCE-HOLE-012
- **Trigger:** external audit, `MILEXIUM_INTERNAL_AUDIT_2026-07-26.md`

## Context — the hole was mine, and worse than reported

Earlier this week `test_realdata_governance.py` was rewritten to assert path
existence only for **git-tracked** paths, because the estate deliberately
gitignores raw zones and large panels and asserting on them broke CI portability.
The motive was right. The closing assertion was:

```python
assert checked >= 1 or all(not (rel.rstrip("/") in tracked) for rel in recorded)
```

**When `checked == 0`, every recorded path is untracked by definition, so the
`all(...)` is trivially true and the assertion cannot fail.** The audit found it
by repointing a manifest at a nonexistent ignored directory and watching the test
pass.

It is worse than an edge case: **three of the five legacy manifests
(`chicago-tnp`, `mta-afc`, `nyc-tlc`) record zero git-tracked paths**, so for
those the entire test asserted nothing at all. The docstring said *"a governance
record pointing at nothing is worse than none, because it looks like coverage"* —
and then failed to enforce exactly that.

## Decision — per-path classification, each with a named failing case

| path is | rule |
|---|---|
| tracked | must exist → `CASE tracked-but-missing` |
| neither tracked nor ignored | must exist → `CASE unexplained-absence` |
| ignored | the ignore rule must live in a **git-tracked** file → `CASE uncommitted-excuse` |
| ignored + absent | must anchor to an existing nearest tracked ancestor (`CASE unanchored`) **and** no sibling recorded ignored path in the same zone may be present (`CASE fictional-in-a-materialised-zone`) |

The zone rule is the closure: **if a sibling dataset's ignored bytes are on this
disk, "absent by design" is no longer an available excuse.**

When nothing can be verified the test **prints** `NO PATH VERIFIED IN THIS
CHECKOUT` rather than asserting — a summary assertion is precisely the shape that
went vacuous in the first place.

**Proved, not asserted.** Chicago repointed at a nonexistent gitignored directory:
the old logic replayed verbatim reports `PASS (paths checked for existence: 0)`;
the new logic **fails** with `CASE fictional-in-a-materialised-zone`, naming the
three present siblings as evidence. Portability was checked with a real
`git clone --local` into scratch, not a simulation: 17 passed, with the three
unverifiable manifests printing their gap.

## The packet's own plumbing was silently broken first

Batching paths through `git check-ignore --stdin` with `text=True` appends `\r` on
Windows; git C-quoted them back and **every lookup missed**, so the probe failed
with the *wrong* case while looking correct. **That would have been the ninth
vacuous test this month.** `test_the_ignore_rule_lookup_actually_resolves_paths`
now cross-checks the batched lookup against per-path `check-ignore -q`.

## The audit's root cause for defect 2 was wrong

The audit attributed the non-reproducible weather result to a mutable upstream
source. **Measured instead of assumed: a full live re-fetch returned a
byte-identical observation set** (25 stations, 3,300 station-months, same
sha256). The arithmetic names the real cause — every agency contributes exactly
108 complete agency-months, and `1994 − 1886 = 108`, `20 − 19 = 1`. **One
station's fetch failed transiently; the old code dropped it, kept the rest, and
cached the result** — silently redefining the sample and then freezing it.

Fixed by pinning: `forge/research/h3_weather_observations.json` is committed and
content-hashed; the default path reads only the pin, with **no network and no
cache fallback**. `--verify` is the drift check; `--refresh` is a separate
explicit action that prints a station-by-station delta and **refuses to write a
pin missing any declared station** unless `--allow-partial` says so in the open.
Six mutations confirm it, including replacing `urlopen` with a raising stub —
still VERIFIED, which proves there is no silent fetch.

The 172 KB gitignored cache is deleted; the 150 KB pin is committed, because a
result nobody can regenerate is not a result.

## Consequences

**48 passed** across the two governance suites (17 in the repaired file, up from
16); 233 across estate/manifest/panel selection. No test weakened.

## Holes deliberately left open

- **The rights test is still fabricable** — a manifest asserting "commercial use
  is permitted because this sentence says so" passes. The honest fix is a captured
  licence URL, terms hash and timestamp **in the manifests**, which this packet
  does not own; a keyword whitelist would either fail all five legacy manifests or
  move the fabrication one word sideways.
- **On a clean checkout, an all-ignored manifest still passes.** Closing it needs
  committed per-file inventories — manifest content, not test logic.
- A manifest whose only recorded path has no ignored peer in its zone can never
  trip the materialisation rule.
- `h3b_seasonality` and `h4_census_unmet_need` share the unpinned-cache shape; the
  audit found they reproduce, so they were left.
- Nothing here is **Validated**: the test is Demonstrated against six mutations on
  two checkout shapes, the artifact Demonstrated reproducible on one machine.
