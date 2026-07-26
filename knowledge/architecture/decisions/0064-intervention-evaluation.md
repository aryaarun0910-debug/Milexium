# ADR-0064: Evaluating an intervention without being able to prove it caused anything

- **Status:** Accepted
- **Date:** 2026-07-26
- **Packet:** MX-H-INTERVENTION-EVAL-010

## Context

A senior paratransit consultant, engaged on newly-installed AI scheduling systems
at several agencies, wrote to us:

> *"there is insufficient new data to support any conclusion that the new software
> has done any better, but I am persuaded that they are on the right track"*

— while reporting that those systems "yielded improved on-time performance;
reduction in cost due to greater efficiency... and more effective management of
capacity."

**Both halves are true at once, and the gap between them is the product.** An
agency swaps schedulers, OTP improves, and nobody can separate the software from
the weather, a service change, a fleet change, a demand shift, or regression to
the mean after the bad quarter that triggered the procurement.

## Decision

A pre/post evaluation that is **structurally incapable of claiming causation**.

- **`EvidenceStrength` has no `"causal"` value.** `causal_proof=True` raises;
  `is_randomised_experiment=True` raises. The strongest reachable verdict is
  `"association_only_confounders_addressed"`, and reaching *that* requires a
  difference-in-differences design with **zero unresolved confounders**. There is
  no arrangement of inputs that types a stronger claim. This is the ADR-0039
  discipline applied to a new surface: the refusal lives in the type, not the
  docstring.
- **Pre-registration.** `pre_register` / `pre_register_family` fix the metric, the
  window and the expected direction **before the post-period is read**, and record
  them in the output. Retrospective metric-shopping is how vendor evaluations get
  their numbers.
- **Confounders are surfaced, not buried.** Unresolved ones are lifted to a
  top-level `unresolved_confounders` field. Where history was not supplied, the
  output says the confounder *cannot be ruled out* rather than staying silent —
  silence reads as "addressed".
- **Regression to the mean has its own block**, because it is the single most
  likely way a real evaluation misleads: an agency that procures after a bad
  period improves *somewhat* regardless.
- Difference-in-differences against peer control series is supported and labelled
  as **stronger association and still not an experiment** — it rests on a
  parallel-trends assumption that is stated rather than assumed away.

## Consequences

**73 tests** (64 + 9), including runs against the real NTD panels. Full repo
suite **2337 passed, 1 skipped**.

`app/replay/teardown.py` is **byte-identical** — ADR-0056's central claim and
its pinned benchmark numbers survive this packet untouched.

## Honest limitations

- **Nothing here is Validated.** Public NTD panels and synthetic series support
  *method* claims only. No consented operator data exists, so no evaluation in
  this repo describes a real intervention at a real agency.
- **A parallel-trends assumption is still an assumption.** DiD is stronger than
  uncontrolled pre/post and is not identification. If the treated agency was
  already diverging from its controls, the design cannot see it.
- **Confounder coverage is a list, not a proof.** We enumerate seasonality,
  concurrent service change, demand-mix shift, fleet change and regression to the
  mean. A confounder nobody named is not detected, and the output cannot know
  what it was not told.
- **Monthly NTD granularity is coarse** for an intervention whose effect may be
  weekly or daily. A real evaluation would want operational records, which is
  precisely what we do not yet have.
