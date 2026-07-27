# YC Fall 2026 — final answers, copyable

Every figure below is computed from `forge/business/ntd/agency_economics.csv`
(NTD 2024 report year, 1,920 demand-response reporters) or quoted from a named
public source. Recompute with `forge/business/ntd/build_economics.py`.

**One correction to the previous draft is folded in:** the market-size answer
said "low hundreds of millions" against a per-vehicle price. At $40–80/vehicle/
month over the 44,424 demand-response vehicles in maximum service that is
**$21M–43M**, not hundreds of millions. Rebuilt below on a pricing basis that
survives the arithmetic.

**Batch dates (verified against ycombinator.com/apply):** Fall 2026 runs
**October to December 2026**, in person in San Francisco, opening with a 3-day
kick-off. Demo Day is Wednesday 2 December. On-time application deadline is
**27 July, 8pm PT**; decisions by 28 August. The "October" in the
school-balancing answer is correct — an earlier note in this repo said
14 September and was wrong.

---

## Please provide a link to the product, if any.

https://milexium.com

The site carries the architecture, the forecast leaderboard with every model
shown against its own seasonal-naive baseline, and the sample evidence pack. No
login. There is no self-serve product yet — the deployable artifact today is a
shadow-mode run against an operator's own booking export, which we run with the
operator rather than ship as a signup.

---

## Why did you pick this idea to work on? Do you have domain expertise in this area? How do you know people need what you're making?

We started in November 2025 with a university project on bus routing. The
optimisation part was solved and boring — OR-Tools does it. What we could not
find anywhere was a system that could say *why* it made a given scheduling
decision in a way that survived someone checking. So we went looking for the
place where that question is not academic, and found paratransit: ADA-mandated
door-to-door transport for elderly and disabled riders, where a scheduling
decision is a legal event and every denial is reviewable under 49 CFR § 37.

We do not claim operating expertise — neither of us has dispatched a fleet. What
we have is that we read the federal record harder than the people selling into
this market appear to have. The single finding that made us commit:

FTA's 2020 ADA compliance review of Memphis Area Transit Authority. MATA
reported a denial rate of **2.3%** for FY2019. FTA's reviewers sat in the
reservations centre, listened to 74 trip requests, and measured **27%**. On a
second sample of 46 requests they measured **37%**. An order of magnitude, at a
named agency, in the regulator's own words.

SEPTA's 2018 review shows the mechanism. SEPTA told FTA it had a "zero-denial
policy — all trips are negotiated to a time within one hour of the request." FTA
found trips negotiated outside that window, which are denials by regulation, and
recorded that **SEPTA does not track them**. The number is not falsified. The
definition absorbs it, at the moment of scheduling, and nothing downstream can
recover it.

That is the product. Not better forecasting — an operator that cannot see its
own denial rate cannot be sold accuracy. A tamper-evident record of what was
decided, what else was possible, and which constraint bound, written at the
moment the decision is made, because that is the only moment the information
still exists.

There are **84 such reviews across roughly 78 named agencies**, 2000–2021, with
14 agencies reviewed twice — before-and-after pairs at the same operator. It is
third-party, adversarial, regulator-issued evidence that the problem is real,
recurring, and systematically under-reported. We did not have to assume the pain;
a federal regulator documented it.

On need: this is where we are behind and know it. We have a scheduled call with
an operator on 31 July and correspondence open with a former WMATA accessibility
executive. We have no signed design partner and no consented operator data. We
would rather say that than describe two conversations as validation.

---

## Who are your competitors? What do you understand about your business that they don't?

The incumbent dispatch platforms are **Ecolane**, **TripSpark**, and
**RouteMatch** (acquired by Uber Health) — systems built 15–20 years ago, before
explainability was a category anyone asked for. NEMT brokers such as
**Modivcare** and **MTM** are channel partners or competitors depending on how
the market consolidates.

Three things we think they have wrong.

**Forecast accuracy does not cause a procurement.** These are compliance-heavy,
publicly funded operators with procurement cycles measured in years. An entrant
selling "AI for transit" is asking a general manager to stake their dispatch
system on a startup. We sell a shadow-mode evidence layer that runs alongside
whatever they already have and touches nothing. The incumbent stays. That is not
a weaker sale — it is the only sale available to a company with no operating
history.

**Auditability cannot be retrofitted.** An audit trail is a constraint on how the
decision is *computed*, not a log written afterwards. To reconstruct why a trip
was denied you need the exact information set the scheduler held at that instant
— what was known, what was not yet known, which vehicle was where. Our verifier
re-derives that from primitive rows and runs in an interpreter that cannot
import our own code, so a passing check is not us marking our own homework. An
incumbent adding this would be rewriting the core of a product thousands of
agencies depend on daily, to sell a feature none of their customers has yet put
in an RFP.

**The under-reporting is the wedge, and it is not a bug in their software.** It
is definitional, and it happens at the point of scheduling. Every one of those
84 FTA reviews is a case where an operator's own numbers did not survive a
regulator. When it becomes an RFP line item — and DOJ enforcement suggests it
will — the operators who lose are the ones who cannot produce the record. We
are building the record.

---

## How do or will you make money? How much could you make?

Per-vehicle-per-month SaaS billed on vehicles in maximum service, which is how
Ecolane, TripSpark and RouteMatch are already procured, so it needs no
procurement education.

The bottom-up numbers, from every US demand-response operator's own federal
filings (NTD 2024, 1,920 reporters):

| | agencies | vehicles | annual trips | annual opex |
|---|---:|---:|---:|---:|
| **All DR reporters** | 1,920 | 44,424 | 139.7M | $7.06B |
| **Over 200k trips/yr** | 121 | 21,863 | 75.1M | $4.44B |
| 50k–200k | 439 | 12,609 | 41.1M | $1.67B |
| Under 50k | 1,360 | 9,952 | 23.5M | $0.95B |

**The beachhead is 121 agencies.** They run 49% of all demand-response vehicles
and 63% of the sector's operating expense. At $75/vehicle/month that is roughly
**$163k average contract value** and about **$20M ARR** if we won all of them —
a real enterprise sale into a countable list of named buyers, each with a public
filing we have already read.

**Priced across all 1,920 NTD reporters**, per-vehicle SaaS is **$21M–43M** at
$40–80. We are stating that plainly because it is the number a partner will
reach for, and it is the reason the per-vehicle basis is a beachhead price
rather than the business. Benchmarked as a share of the $7.06B these agencies
already spend running the service, transport-management software at 1–2% of
operating expense is **$70M–140M** — and that is the ceiling of the public
demand-response market alone.

**Where it actually gets large is NEMT.** Medicaid-funded non-emergency medical
transport is a **~$15B market** growing at roughly 9% a year, of which Medicaid
NEMT is around **$3B annually** serving 3–4 million beneficiaries. NTD covers
only FTA-funded public transit; the NEMT provider population is an order of
magnitude larger and its audit exposure is worse, because every trip is a
reimbursement claim against a payer that can claw it back. A tamper-evident
record of why a trip was scheduled, denied, or missed is worth materially more
to someone billing Medicaid than to a transit agency defending a compliance
review. Same product, same evidence pack, larger and better-funded buyer.

First customers are priced as paid pilots covering integration cost rather than
list price, because the consented operational data is worth more than the
licence fee at this stage.

**We do not price on savings or outcomes.** Our own analysis cannot separate
avoidable from structural cost in an operator's numbers — deadhead share has
essentially no relationship to cost per trip (Spearman +0.024 across 406
operators, against +0.738 for cost per hour). Charging on a figure we cannot
defend would contradict the entire product.

---

## What convinced you to apply to Y Combinator? Did someone encourage you to apply? Have you been to any YC events?

> **Arya — check the factual clauses in this one before sending. I have drafted
> the reasoning; the "who encouraged you" and "events" sentences must be true
> for you and Chris specifically. Delete what does not apply.**

Two things.

The first is that we are two second-year engineering students in the UK trying
to sell to American public agencies. Every part of that is a disadvantage we
cannot fix by working harder — we cannot get a meeting with a transit general
manager in Denver from a Loughborough halls room on credibility we do not have.
YC is the shortest path we know from no standing to a warm introduction, and the
alumni network includes people who have sold into public-sector procurement and
survived it.

The second is more specific. We have watched YC fund companies whose first
version was one narrow thing done properly rather than a platform. That matched
what we had already decided to do: not to replace anyone's dispatch system, just
to make one decision reviewable, and to be honest about the difference. We would
rather be pushed hard on that by people who have seen a thousand of these than
keep finding it out ourselves at university pace.

We have not attended a YC event. We have worked through Startup School and the
YC library, and read the Requests for Startups.

---

## How did you hear about Y Combinator?

> **Arya — replace with whichever is actually true. Draft below assumes Hacker
> News, which is the most common honest answer for engineers.**

Through Hacker News, which we both read before we knew it was run by YC. The
Startup School material and the YC library came later, and are what turned it
from a name into something we understood well enough to apply to.

---

## Equity — the answer, and why 50/50 is right

**Copyable answer:**

No legal entity has been formed yet. We will incorporate a Delaware C-Corp on
acceptance.

Planned split: **Chris Legge (CEO) 50%, Arya Arun (CTO) 50%.** No other
stockholders, employees or advisors. Both founders on a standard **4-year vest
with a 1-year cliff**, running from incorporation, applied equally to both of
us. No option pool until we make a first hire.

We considered weighting it. Arya wrote most of the current codebase; Chris built
the site, the infrastructure and the early hardware work, and carries the
commercial side. Neither of us thinks that difference will still be legible in
two years, and both of us think the person who would be diluted for it would be
right to resent it. All the work is ahead of us. An unequal split would be us
telling you we do not fully rate one of our own founders.

**On dilution: 50/50 is unaffected by taking investment.** Founder splits are
relative to each other. Any round dilutes both of us in exactly the same
proportion — after YC's standard $125k for 7% we hold roughly 46.5% each, still
equal. The split is not a claim on the cap table's future shape; it is a
statement about which of us is replaceable.

### Why I recommend this (research, not opinion)

You asked whether 50/50 is really possible with investors on the cap table. Yes
— and the question contains the misunderstanding worth clearing up:

- **Dilution is pro-rata and hits both founders identically.** If you each hold
  50% and sell 7% to YC, you each hold 46.5%. You are still equal. There is no
  mechanism by which investors make an equal founder split unequal.
- **YC actively recommends equal splits.** Michael Seibel's line is the blunt
  version: *"If you aren't willing to give your partner an equal share, then
  perhaps you are choosing the wrong partner."* YC's stated reasoning is that
  splits weighted for who had the idea or started first over-reward the past and
  under-reward the years of execution that actually build the company.
- **An unequal split is a negative signal in the application itself.** YC's own
  guidance asks why you would tell investors your team contains someone you do
  not value highly.
- **Vesting is the thing that actually protects you, not the percentage.** A
  4-year vest with a 1-year cliff means a founder who leaves in month eight
  leaves with nothing, and one who leaves at month eighteen keeps a quarter. Put
  it in place at incorporation and the 50/50 costs you nothing in the case you
  are worried about. Skip it and no split protects you.
- **YC's standard deal, for the arithmetic:** $500k total — $125k for 7% on a
  post-money SAFE, plus $375k on an uncapped MFN SAFE that takes the terms of
  your next priced round.

The one thing to settle *before* you submit: **Chris is listed as CEO.** Make
sure that is a decision the two of you have actually made out loud, because YC
will ask each of you separately and a mismatch there is far more damaging than
any split.

---

## Where this goes — the frontier

> Use this for the "what will you make" long answer or in interview. It is the
> answer to "why is this a big company and not a compliance tool."

**Now — the decision record.** Forecast, schedule, and a tamper-evident evidence
pack per decision. Shadow mode, alongside the incumbent, touching nothing.

**Next — agent workers on the ontology.** Six roles, each bound to the canonical
data model, each able to emit only figures that carry a source, none holding
authority to alter canonical state: intake (maps a new operator's export and
flags what it could not map), dispatch (surfaces the run about to breach its
window), capacity (answers why a zone is at risk at 14:00 from the ontology
rather than from memory), appeals (assembles the denial record a rider or
advocate has requested), compliance (maps operations to 49 CFR § 37 and names
what would fail a review), fleet (reads telemetry and proposes repositioning
before the gap opens). The constraint is what makes it sellable into a regulated
buyer: an agent that cannot invent a number is one a general manager can put in
front of an auditor.

**Next — write-back.** Approved actions update the operator's dispatch system and
the loop closes end to end. This is the point the product stops being an
observer and starts being infrastructure, and it is the point pricing moves off
the pilot floor.

**Then — the edge.** Paratransit runs in places cellular does not reach, and a
vehicle that loses its link stops being schedulable. On-board FPGA compute
evaluates route feasibility at the vehicle with a deterministic latency budget
and no round-trip; a sub-GHz **LoRa** uplink carries state where there is no
cellular contract to buy, at roughly a fortieth of the bandwidth because the
filtering happens on board and full fidelity stays local. Store-and-forward means
a blackspot delays the record rather than destroying it. Arya's course is
Computer and Electronic Engineering and his internship is in medical device
tagging — this is the part of the roadmap we are least likely to get wrong.

**Adjacent markets, same product.** NEMT brokers and providers (larger, better
funded, worse audit exposure). Special-needs school transport — legally
identical: an individual entitlement, a routing problem, and a district that has
to defend it. Rural microtransit. Hospital discharge transport, where a missed
ride is a readmission.

**The asset that compounds.** Every consented decision episode is a labelled
record of state, action, alternatives and outcome. No incumbent has that,
because none of them recorded the alternatives. It is the training data for the
next model and it is not purchasable — it only exists if you built the evidence
layer first. That is why the boring compliance wedge is the right first move and
not a smaller ambition.

---

## Still to do before submitting

- [ ] Founder video (script locked; record from it)
- [ ] Demo video — use `aletheia/artifacts/reel/recording/milexium-system.mp4`
- [ ] "Something impressive each founder has built" — genuinely personal, needs you
- [ ] "Hacking a system" answer — needs you
- [ ] Xtag Medical: add description, and set an end date (currently "current
      position" against a "Yes" exclusivity answer — that conflict will be noticed)
- [ ] Confirm with Chris out loud: CEO title, 50/50, 4-year vest / 1-year cliff
- [ ] EWB IP check if any of the routing work touched university-owned material

## Sources

- [YC — How to Split Equity Among Co-Founders](https://www.ycombinator.com/blog/splitting-equity-among-founders)
- [YC Startup Library — How to split equity among co-founders](https://www.ycombinator.com/library/5x-how-to-split-equity-among-co-founders)
- [YC's $500,000 Standard Deal](https://www.ycombinator.com/blog/ycs-500-000-standard-deal)
- [The Y Combinator Deal](https://ycombinator.com/deal)
- [KFF — Medicaid Non-Emergency Medical Transportation](https://www.kff.org/medicaid/medicaid-non-emergency-medical-transportation-overview-and-key-issues-in-medicaid-expansion-waivers/)
- [Milliman — The road to care: NEMT delivery systems](https://www.milliman.com/en/insight/the-road-to-care-non-emergency-medical-transportation)
- [FTA ADA compliance review final reports](https://www.transit.dot.gov/regulations-and-guidance/civil-rights-ada/ada-compliance-review-final-reports)
- NTD 2024 (datasets `ekg5-frzt`, `wwdp-t4re`, data.transportation.gov) via `forge/business/ntd/`
