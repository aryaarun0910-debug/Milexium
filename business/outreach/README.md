# business/outreach/

The design-partner funnel: target research, the copy that goes to them, and the
record of what was sent.

**Read `design_partner_pitch.md` first.** It is the strategy every file here
serves, and its rules are binding — in particular *"send ~10-15/day, not a bulk
blast"*, because each organisation is a one-shot and there are only ~109 US
agencies in the target profile.

## ⚠️ STOP — the deadhead hook is diagnostically dead (2026-07-26)

**`build_peer_insight.py` and `generate_v3_emails.py` lead with an agency's
national deadhead rank. That metric does not identify an expensive agency.**

Measured twice, independently:

- Spearman **+0.024** between deadhead share and cost per trip across 406
  operators, against **+0.738** for cost per *hour*, with cost-per-trip
  **quartile** medians flat at **$48.53 / $53.34 / $52.30 / $54.09**
  (`panel_findings.json`, finding `dr_deadhead_predicts_cost_per_trip` in the
  `rejected` list).
- Pearson **+0.017**, OLS **R² = 0.0003**, n=405
  (`research/h5b_structure_vs_cost.json`).

The *arithmetic* cost of empty running is still real, as an accounting
identity. The **diagnostic** claim — that a high deadhead rank means an agency
has a cost problem — is false, and every v3 agency email is built on it.

**What replaces it:** occupancy. Ride-sharing collapsed **−10.0%** 2015→2024
(1.213 → 1.092 passenger miles per vehicle mile) while trips got *shorter*, not
longer; 66.8% of agencies lost occupancy and recovery has stalled
(`research/h5e_ridesharing.json`). Occupancy is what a scheduling optimiser
actually sets, which makes it both the better diagnosis and the one our product
speaks to. **Scope it to large operators** — the passenger-miles filers are a
non-random 26% of agencies by count, though 66% by trips — and note that the
closely related pooling claim was **rejected** by the panel gate
(`dr_pooling_efficiency_declined`, on effect size and composition). Occupancy
clears the 5% effect floor where trip length does not, but it inherits the same
Full-Reporter selection bias, so it is a scoped hypothesis for shadow mode, not
a sector finding.

Do not send another deadhead-ranked agency email until the peer engine is
rebuilt on occupancy.

### The dollar figures are already gone (MX-CLAIMS-DOLLAR-SWEEP-013)

The *rank* is still deadhead. The *money* is no longer anywhere. Every savings
and opportunity dollar claim in `business/ntd/` and `business/outreach/` has been removed:

| was | now |
|---|---|
| `business/ntd/savings_calculator.py`, the public-website widget | removed; `business/ntd/peer_position.py` returns a national position instead |
| "A 10 percent deadhead reduction is worth about $X a year to you" | the agency's percentile on cost per trip, cost per revenue hour and trips per revenue hour |
| "closing even a quarter of that gap is worth about $X a year" | removed outright — it assumed the gap to the median is recoverable |
| "$94,399,949 per year" in `business/ntd/market_sizing.md` | the same total, labelled an accounting identity, plus the null result beside it |
| "At your cost per hour the gap is roughly $X a year" (v3) | the operator's cost per revenue hour against the same peer group |
| `value_10pct_deadhead_cut`, `modelled_gap_value_usd`, `deadhead_dollars_per_yr` | columns and fields deleted, so the number cannot be rendered by accident |

**The standing rule.** A dollar figure may appear only when it is arithmetic on
the agency's own filing — "these empty vehicle-hours cost $X at your own
reported cost per hour" — and only while labelled an accounting identity that
states recoverability is unknown. Never as a saving, an opportunity, or a
benefit of adopting Milexium. `app/replay/teardown.py` refuses to emit a
savings envelope without the operator's own fixed/variable split; copy does not
get a lower standard than code. Enforced by
`evidence/conformance/property-tests/test_claim_discipline.py`.

**13 agencies were already sent a dollar figure** (10 on 2026-07-24, 3 on
2026-07-21), and a 14th organisation that opted out was contacted before that.
Their `email_hook` values in `contact_research_worksheet.csv` are **preserved
verbatim** and must stay that way — that column is the record of what they
actually received, and the same test fails if it is ever rewritten.

## The one rule that matters most

**Never send to a shared inbox when a named human is available.** The first
reply we ever received was a decline from an assistant on
`transportation@aacounty.org`; the operations contact never saw it. Shared
inboxes route to people whose job is to triage. `contact_confidence` and
`is_named_person_inbox` exist in the target files for exactly this reason.

`do_not_contact` in the worksheet is **permanent and structural** — it is a
column, not a status string, so no later merge can quietly return an
opted-out organisation to a follow-up queue.

## What is current

| File | What it is |
|---|---|
| `design_partner_pitch.md` | **The strategy.** Funnel, targeting, objection handling, sending discipline |
| `craft_notes.md` | The researched copy rules (length, subject lines, CTA type) with sources. Written after checking the evidence, not from folklore |
| `contact_research_worksheet.csv` | **The record of truth.** 109 agencies: NTD economics, verified contacts, `email_source_url`, send status, `do_not_contact` |
| `build_peer_insight.py` | Computes each agency's **national peer rank** — the hook they cannot see from inside their own data. Has an honesty gate: a sub-2.5-point gap at mid-rank emits nothing rather than a manufactured finding |
| `generate_v3_emails.py` | Generates the agency emails from those insights. Hard-blocks targets whose numbers are not trusted, and deletes any stale draft for them |
| `peer_insights.json` | Generated by `build_peer_insight.py`. Committed so a claim in a sent email can be traced back |
| `build_panel_findings.py` | Computes **sector-level findings about the whole US demand-response panel** — the artifact for domain experts, who do not need one agency's rank. Four-check gate, far stricter than the peer engine's |
| `panel_findings.json` | Generated by `build_panel_findings.py`. Committed. **Read the `rejected` list before the `survived` one** |
| `generate_expert_emails.py` | The expert/consultant segment, built on panel findings. Refuses to write any draft containing a number it cannot trace back to `panel_findings.json` |
| `research/` | Per-person outreach briefs. **Input, not output** — the generators read them; nothing regenerates them |
| `startup_integrator_template.md` | The company/integrator segment — a different pitch, since the NTD hook does not exist for a private firm. Carries the **do-not-contact-competitors** rule |
| `targets_startups_west.csv` | 32 West-coast transit-tech companies, segmented A / B-COMPETITOR / C |
| `targets_small_companies.csv` | 36 small firms and solo founders, with named-vs-shared inbox flagged |
| `expansion_candidates.csv` | 20 net-new agencies the peer engine found beyond the original list |
| `drafts/` | Generated `V3_*.txt` (one per contactable agency) and `EXPERT_*.txt` (one per contactable consultancy). **Gitignored and disposable** — regenerate with the two generators. A *missing* draft is meaningful: held and blocked targets have theirs deleted on every run |

## The founder's originals, still in use

`cold_email_template.md`, `generate_design_partner_emails.py`,
`build_contact_worksheet.py` and `targets_ntd.csv` predate the v3 rewrite and are
still referenced by the pitch document and each other. They are **not** dead —
the v3 generator supersedes the *copy*, not the funnel they describe.

## Tone (v3.1)

Appreciation first where it is genuinely earned, the recipient's **perspective**
as the ask, and an easy exit. The earlier close — "Want it?" — was terse to the
point of brusque; the research says a low-friction *interest-based* ask beats a
meeting request, which is not the same as being curt. The register evidence came
from the first reply we received, which signed off *"Have a great day. Take care."*

Do not fabricate the appreciation. Where there is no public body of work to
credit (a sales lead rather than a builder), lead with their customers' problem
instead — manufactured gratitude is obvious and worse than none.

## Two hooks, two audiences

The peer engine and the panel engine are not versions of each other.

- **Operators get a rank.** A director cannot see where their agency sits
  nationally, so the rank is genuinely new information about them.
- **Experts get panel structure.** Ranking agencies is what a consultant does
  for a living; a rank of an agency that is not theirs is not about them at
  all. What they cannot cheaply get is the shape of the national panel.

`panel_findings.json` carries a `survived` list and a `rejected` list, and the
rejected one is the more valuable half. A gate that never rejects anything is
decoration, so the findings we killed — with the numbers that killed them —
are what shows the surviving ones were tested rather than selected. We have
already sent a rejected finding to a prospect for exactly that reason.

Every finding must pass **mode_provenance** (a demand-response claim needs a
demand-response denominator), **composition** (same agencies at both endpoints,
or the aggregate moved because the membership did) and **concentration** (the
per-agency median printed beside every aggregate, plus leave-one-out over the
largest contributors). Money-over-years additionally needs **inflation** (the
CPI-deflated change beside the nominal one), and any claim that something is
specific to demand response needs **control_mode** against fixed-route bus. A finding
that never *ran* a required check is rejected for that reason alone — silence
is not a pass.

## Holds are not opt-outs

`do_not_contact` is permanent and structural. A **hold** is a reversible
sequencing decision recorded in `status`, and the two must never be conflated:
downgrading a hold into an opt-out burns a valid target forever, and promoting
an opt-out into a hold is worse. Currently held, all pending a human decision:

- **PSTA** and **County Connection (CCCTA)** — both published clients of the
  consultant whose warm reply is open. Enforced in `generate_v3_emails.py`.
- **Foursquare ITP** and **Christian T. Kent TMC** — his teaming partner, and
  the man himself (he already replied; a cold email from a list would say we
  never read it). Enforced in `generate_expert_emails.py`.
- **RTA / Transit Management of Central Maryland** — operates service *for*
  Anne Arundel County, which opted out. **Not an agent's call in either
  direction**; parked for the founder.

## Regenerating

```
py -3 business/outreach/build_peer_insight.py       # peer ranks     -> peer_insights.json
py -3 business/outreach/generate_v3_emails.py       # agency drafts  -> drafts/V3_*.txt
py -3 business/outreach/build_panel_findings.py     # sector findings-> panel_findings.json
py -3 business/outreach/generate_expert_emails.py   # expert drafts  -> drafts/EXPERT_*.txt
```

`build_panel_findings.py` needs the raw NTD extracts under `data/raw/public/`,
which are gitignored; re-acquire them through the governed estate pipeline.

`archive/` holds superseded material kept for reference, not for use.
