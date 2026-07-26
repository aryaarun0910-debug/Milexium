# ADR-0070: Removing every savings claim, and the opt-out that was not honoured

- **Status:** Accepted
- **Date:** 2026-07-26
- **Packet:** MX-CLAIMS-DOLLAR-SWEEP-013
- **Follows:** ADR-0069 (the status contract), ADR-0058 (the deadhead null)

## Context

ADR-0069 removed a **$94M opportunity** figure from the YC draft. That figure was
not an isolated slip — it was the visible end of a system that *generated* savings
claims and sent them to named transit agencies, all resting on a metric this
week's research destroyed: deadhead share versus cost per trip is Pearson
**+0.017**, OLS **R² = 0.0003**, n=405.

The most dangerous artifact was `ntd/savings_calculator.py`, a self-serve "punch
in your agency, see your own numbers" widget **built for the upcoming public
website**, whose `compute_savings(ntd_id, deadhead_cut_pcts)` handed any visitor a
personalised dollar figure.

## Decision

**Remove the capability, not just the wording.**

| Was | Now |
|---|---|
| `ntd/savings_calculator.py` — the website widget | **Deleted**, filename included; `ntd/peer_position.py` returns a national *position* |
| "A 10 percent deadhead reduction is worth about $X a year to you" | percentile on cost per trip, cost per revenue hour, trips per revenue hour |
| "closing even a quarter of that gap is worth about $X" | **deleted outright** — it assumed the gap to median is *recoverable*, the exact causal claim the platform refuses elsewhere |
| `$94,399,949` in `market_sizing.md` | the total, labelled an accounting identity, with the null result beside it |
| `value_10pct_deadhead_cut`, `modelled_gap_value_usd` | **columns and fields deleted**, so no consumer can reach the number by accident |

`compute_savings()` was removed rather than reworded because its entire purpose
was to produce an unsupported number. The deadhead dollar survives only as an
accounting identity carrying an explicit `"is_a_saving": false`.

**The standing rule:** a dollar figure may appear only as arithmetic on the
agency's own filing, labelled an accounting identity stating recoverability is
unknown. Never as a saving, an opportunity, or a benefit of adopting Milexium.
`packages/replay/teardown.py` already refuses to emit a savings envelope without
the operator's own fixed/variable split — **copy does not get a lower standard
than code.**

## The severity-1 finding this packet surfaced by accident

**Anne Arundel County opted out in writing on 2026-07-25** — "please remove us
from your mailing list" — and is correctly marked `do_not_contact`. But **the
agency email pipeline never read that column.** A draft addressed to
`transportation@aacounty.org`, the exact inbox that asked to be removed, was
sitting in `drafts/` awaiting a send.

`generate_expert_emails.py` always honoured the column; `generate_v3_emails.py`
did not. The opt-out was enforced in one of two pipelines, and the one it was
missing from was the one aimed at agencies. Now enforced at both layers, with the
draft deleted on every run. **Pre-existing, and the closest this project has come
to a genuinely damaging mistake.**

## Consequences

**8 new claim-discipline tests**, scanning Python via **AST over emitted string
literals** rather than raw lines — a line scan cannot distinguish a claim the code
*prints* from a comment recording that the claim was deleted.

**7 mutations, all red after fixes. Two exposed real weakness in the packet's own
tests:**
- Overwriting a sent record **passed**, because `>= 13` was satisfied by the
  *wrong* thirteen when a 14th row covered for it. Now pins exact names.
- A restored $94M line **escaped** the sweep: a "documenting a retirement"
  exemption was triggered by an adjacent paragraph. The exemption is now opt-in
  via a 4-file allowlist and unavailable to generated artifacts.

**All 13 sent agencies received a dollar figure** — there is no subset that did
not. Three on 2026-07-21, ten on 2026-07-24, the largest $2.1M. Their
`email_hook` values are **preserved verbatim** and pinned by name in the test:
that column is the record of what was actually received, and rewriting it would
destroy the evidence.

## Honest limitations

- **Nothing sent can be unsent.** A 14th organisation — Anne Arundel — received a
  $360,000 figure before opting out.
- **The rank is still deadhead.** Only the money is gone. `build_peer_insight.py`
  still ranks agencies on a metric that does not diagnose cost; rebuilding it on
  occupancy is outstanding, and `outreach/README.md` carries a stop-warning until
  it is.
- **A filtered median was labelled "national"** — computed after a
  `trips >= 20_000` filter, so hooks quoted $36.61 instead of $37.97. Fixed;
  previously sent hooks carry the wrong figure.
- **The model-card generator would have deleted the ADR-0001 status paragraph** —
  same defect class as the two strings ADR-0069 named, worse in effect.
- **Dangling references left untouched:** `packages/replay/teardown.py:82,759`
  justifies its 0.10 default by appeal to the deleted column, which was always
  circular reasoning.
