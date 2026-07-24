# Startup / integrator outreach — email template

**New segment, distinct from `cold_email_template.md` and `design_partner_pitch.md`.**
Those target *public agencies* and lead with the agency's own NTD deadhead-dollar
figure. That hook does not exist for a private company — startups don't file NTD.
So this segment needs its own copy and its own ask.

## Why this segment at all

Milexium is positioned as a **transport decision runtime other software
integrates**, not a dispatch UI. That makes transit-tech companies *potential
integrators and data partners*, not just competitors-or-customers. The agency
funnel is a procurement slog measured in quarters; a small company can reply and
decide in days. Different clock, worth running in parallel.

## Segmentation — do this before writing a single email

- **A / integrator-or-partner → contact.** Microtransit & on-demand operators,
  NEMT brokers and healthcare-transport tech, GTFS/transit-data tooling,
  fleet telematics/AVL, agency analytics & reporting.
- **B / direct competitor → DO NOT CONTACT.** Anyone whose core product *is*
  paratransit dispatch or transit scheduling optimization. A cold email
  describing our architecture to them is free competitive intelligence. This is
  the single biggest own-goal available in this segment.
- **C / adjacent-but-weak → skip.** Consumer apps, micromobility, EV charging,
  parking.

## The ask (different from the agency funnel)

Agencies: cold email → 15-min call → free de-identified analysis → design
partner. For companies the ask is **an integration or data conversation between
peers**, not a sales call. We are not asking them to buy; we are asking whether
our layer is useful under their product, and whether their operational data
could ride on it. Symbiotic or nothing.

## What actually differentiates us to a technical founder

Not "we have an ML model" — everyone says that, nobody believes it. The
differentiator is **verifiability**, which is checkable in a way model claims
are not:

- decisions emit a **tamper-evident evidence pack a third party re-verifies
  without us** (hash-chained ledger; a Rust verifier byte-for-byte parity-tested
  against the Python reference);
- core invariants are **machine-checked by an SMT solver** (state machine has no
  illegal reachable transition; the hash chain is tamper-evident);
- benchmarks are **reproducible and publish their own losses** — a real
  seasonal-naive comparison per model, including the one where the naive
  baseline wins.

## Honesty rules (non-negotiable, same as everywhere else)

- Status is **Demonstrated on real public data** — NOT operator-Validated.
  Say so in the email. Volunteering the limitation is disarming, and a technical
  founder will find it in ten minutes anyway; being the one to raise it first is
  worth more than the sentence costs.
- Never imply we have a live operator pilot, a customer, or revenue.
- Never send the same email to a competitor "just to see."

---

## Variant A — founder / CTO at a small company (default)

Subject: `Forecasting + verifiable decision layer under [Company]?`

Hi [Name],

[ONE line, specific and recent — the funding round, the launch, the city they
just won. If you can't write this line honestly, don't send the email.]

I'm Arya, an engineering student at Loughborough in the UK. With my teammate
Chris I've been building Milexium — a decision layer for demand-response
transit. Demand forecasting on real public data (NYC Access-A-Ride, Chicago,
MTA) with calibrated prediction intervals, and the part I think is actually
novel: every decision emits a tamper-evident evidence pack that a third party
can re-verify without us, and the core state machine and hash chain are
machine-checked with an SMT solver.

It's built to sit *under* other software rather than be another dispatch UI —
which is why I'm writing to you instead of pitching an agency.

Straight about where we are: it's demonstrated on public data, we don't have an
operator pilot yet, and I'm not going to pretend otherwise.

Worth 15 minutes to see whether there's an integration — or a data swap — that's
useful to you?

Thanks,
Arya

---

## Variant B — Head of Partnerships / BD

Same substance, less architecture, more "where this fits commercially."

Subject: `Possible integration — forecasting + audit trail for [Company]`

Hi [Name],

[ONE specific, recent line.]

I'm Arya, an engineering student at Loughborough (UK), building Milexium with my
teammate Chris. We've built a forecasting and decision-evidence layer for
demand-response transit: it predicts demand from an operator's own data and
produces an independently verifiable audit trail for every scheduling decision —
which is the part agencies keep asking about for ADA and NTD reporting.

We're deliberately a layer other platforms integrate, not a competing dispatch
product, so [Company] would be a partner rather than a customer.

To be straight: we're demonstrated on public data and don't have an operator
pilot yet. I'd rather say that up front than discover it matters on call two.

Is there someone on your side it's worth me spending 15 minutes with?

Thanks,
Arya

---

## Sending discipline (inherits `design_partner_pitch.md`)

- **Drafts only, reviewed by a human, sent in small batches.** No auto-blast —
  same rule as the agency funnel and for the same reasons (deliverability, and
  each company is a one-shot).
- Fill `[Name]` and the personalization line **for real**. A template that
  obviously wasn't read is worse than no email.
- ~10-15/day from the real Gmail.
- Log every send in the worksheet so follow-ups don't collide.
