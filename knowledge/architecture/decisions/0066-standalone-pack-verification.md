# ADR-0066: A pack you can check without trusting us

- **Status:** Accepted
- **Date:** 2026-07-26
- **Packet:** MX-I-THIRD-PARTY-VERIFY-010

## Context

The evidence pack is the platform's punchline: a third party should be able to
check our claims **without trusting us**. If verification requires our code, our
database or our goodwill, it is not verification — it is a report.

ADR-0045 already found the failure this exists to prevent: a pack that *claimed*
a redaction it had not performed. The lesson recorded there was "enumerate the
data, never the places."

## Decision

`app/evidence/standalone_verifier.py` — a verifier that walks a pack file and
re-derives its claims from the primitive rows it carries, rather than reading a
stored answer and echoing it.

**Re-derivation, not restatement.** The narrative (`evidence`) is treated as a
*reorganisation* of the ledger: every event it cites is matched to its raw row by
`event_id`, and **every field the record happens to carry is compared** — not a
remembered list of fields. That is ADR-0045's lesson applied structurally, and it
catches an edit the per-event hash cannot see: `occurred_at` is not an input to
the event hash, so an attacker who changes it and re-anchors the bundle checksum
passes the chain check and fails this one.

**The chain is walked, not just recomputed.** `_check_chain` both recomputes every
event hash from the raw rows *and* re-walks the `prev_hash` links.

## Consequences

**47 tests.** Full repo suite **2337 passed, 1 skipped**.

### The two tests that exist because a mutation escaped

Both are worth recording, because they are the reason the suite is not vacuous:

- **`test_a_spliced_chain_whose_every_hash_recomputes_is_caught_by_the_links`** —
  written because neutering the *linkage* check left the ordinary tamper test
  green: recomputation catches that one too, so it never proved the links were
  walked. Here a row is re-pointed at a hash that is not its predecessor's and
  its own hash is recomputed correctly for the new `prev_hash`, so every
  per-event hash verifies in isolation and only walking the links notices.
- **`test_a_rewritten_final_hash_is_caught_only_by_recomputing_it`** — the mirror
  case, written because neutering the *recomputation* left the same test green:
  editing a middle row's hash also breaks the next row's link. Here the **last**
  row is edited, so there is no successor to break.

The splice test was **left failing when its agent was killed**, and fixing it
exposed a subtle fixture bug worth naming: the test rewrote the narrative with a
blanket string replace, but the row's original `prev_hash` **is** its
predecessor's own `hash` — the same 64 characters. Replacing it everywhere also
silently rewrote the narrative's copy of the predecessor's `hash`, which the
ledger still held unchanged. The pack then failed `narrative.matches_ledger` for a
reason unrelated to the splice, and the test stopped isolating what it claimed to.
It now edits the narrative field-by-field, addressed by `event_id`.

Mutation-verified after the fix: neutering the link walk fails **exactly** that
test and nothing else.

## Honest limitations

- **"Standalone" is not yet "no Milexium code".** The verifier is a single
  self-contained module a third party can read and rerun, which is a large step
  past "trust our platform" — but it is still *our* module. A genuinely
  independent check means a published algorithm someone reimplements, and that is
  not done.
- The verifier attests **"this computation follows from these inputs"**, never
  "this reflects operational reality". With no consented operator data, a pack
  can be internally perfect and describe nothing that happened.
- Determinism is relied upon for verification to be meaningful; it is asserted by
  tests over the packs we generate, not proven across environments.
- Tamper coverage is a list of cases we thought of. A tamper nobody enumerated is
  not detected.
