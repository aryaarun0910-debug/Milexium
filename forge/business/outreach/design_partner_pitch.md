# Design-partner pitch and strategy

The point of outreach is not "sell software." It is to earn the one thing that
actually makes Milexium defensible: **a real operator's trip-level data,
and eventually the decision-to-outcome loop that no competitor can replicate.**
Public data (NTD, TLC, MTA, Chicago) proves we can build the ML. It is not a
moat, because anyone can download it. The moat is a design partner's own data.
So every email here is engineered to move toward that, one step at a time.

## The funnel (never skip a step)

1. **Cold email** leading with the agency's OWN NTD position: what it costs
   them to move somebody, where that sits among the 1,920 US operators filing
   demand-response service, and the two numbers underneath it (cost per
   revenue hour, trips per revenue hour). The personalized number is the
   pattern-interrupt. Ask: a 15-minute call.
   (generate_design_partner_emails.py produces these, one per agency.)
2. **15-minute call:** listen for where scheduling actually breaks (denials,
   no-shows, late pickups, standing-order chaos). Do NOT pitch a model.
3. **Free analysis offer:** "Send us a de-identified export of your trip data
   and we'll show you exactly which hours and which runs your empty time sits
   in - no cost, no obligation." This is the data-acquisition move. A free,
   specific analysis is a very easy yes, and it hands you the proprietary data.
   **The offer is to locate it, never to price it.** What a fixed hour of
   empty running is worth depends on the operator's own fixed-versus-variable
   split, which is in no public filing; offering to say "what fixing it is
   worth" promises a number nobody can produce and would be caught by the
   first director who knows their own books.
4. **Design partner:** "Be one of our first partners - you shape the product,
   you get founding-partner terms, and you get the audit-trail/compliance
   tooling first." Now you have a logo, a reference, and a live data feed.
5. **The compounding moat:** once deployed, every scheduling decision + its
   real outcome is training data only you have. This is the unassailable part.
   It does not exist until step 4.

## Who to target FIRST (this matters more than the copy)

**Not the giants.** The largest systems (MTA NYC, LA Metro, WMATA, SEPTA) are
the wrong first targets whatever their numbers look like: multi-year
procurement, layers of gatekeepers, will not design-partner with two founders.
Save them for after you have a reference customer.

**Not the micro-operators either.** Rank the national panel on cost per trip
alone and the top of the list is tribal and rural programs filing twenty trips
a year at four figures each. Arithmetically the most expensive operators in the
country; not operations that need a scheduler.

**The sweet spot:** mid-size agencies, roughly **50,000-300,000 annual
demand-response trips**, **at or above the national median cost per trip**, and
organized as a **county/regional authority or non-profit** (they pick their own
software; no state-DOT procurement gauntlet). Big enough to run a real
scheduling operation, small enough that the ops director can say yes to a pilot
themselves.

The old criterion here was **deadhead over 15%**, on the reasoning that a high
empty-hour share meant real money to save. It does not. Deadhead share does not
identify an expensive agency: Spearman **+0.024** against cost per trip across
406 operators, against **+0.738** for cost per *hour*, and cost per trip is flat
across deadhead quartiles at **$48.53** in the lowest against **$54.09** in the
highest (`forge/business/outreach/panel_findings.json`, finding
`dr_deadhead_predicts_cost_per_trip`, **rejected** by the panel gate). Pearson
**+0.017**, OLS **R² 0.0003** at n=405
(`forge/research/h5b_structure_vs_cost.json`). Selecting on it was selecting on noise.

Concretely from the data: agencies like rabbittransit (PA), Delaware Transit,
Denton County (TX), OATS (MO), Suffolk County Transit (NY) - regional
authorities and non-profits in that trip band. Run:
```
py -3 forge/business/outreach/generate_design_partner_emails.py --top 80
```
then work the mid-size regional/non-profit rows first, not the top-10 metros.
Filter by your own state or a target region with `--state XX` to cluster
outreach (easier to reference "we're talking to several agencies in your area").

## The cold email (what and why)

- **Leads with their number, not our bio.** "Your filing puts you at percentile
  75 of 1,920 operators on cost per trip" beats "I'm a student who won a
  competition." The credential goes in one line, mid-email, never the opener.
- **Their position, never a saving.** No email, deck, call or public page
  attaches a dollar figure to the distance between an agency and the national
  median. That distance is not known to be recoverable, and saying it is would
  be the same causal claim the platform refuses to make everywhere else —
  `aletheia/replay/teardown.py` will not emit a savings envelope without the
  operator's own fixed/variable split, and copy does not get a lower standard
  than code. A dollar figure that is pure arithmetic on the agency's own filing
  ("these empty vehicle-hours cost $X at your own reported cost per hour") may
  be stated **only** while labelled an accounting identity and paired with the
  fact that recoverability is unknown. Never as a saving, an opportunity, or a
  benefit of adopting Milexium.
- **Names the real buying trigger:** compliance/defensibility, not efficiency.
  "Every denial comes with the reason, which makes your ADA/NTD reporting
  defensible" is what an ops director actually loses sleep over.
- **Under ~120 words.** Ops managers skim. The number does the work.
- **Two asks, escalating:** the call (low friction) and, inside the same
  sentence, the free data analysis (the real goal, framed as a favor to them).

## Objection handling (for the call)

- *"We already have Ecolane/TripSpark/RouteMatch."* Good - we don't replace
  your dispatch system to start. We run in shadow mode on your existing
  exports and show you what a more explainable layer would surface. No rip-out.
- *"We can't share rider data."* Understood - de-identified is fine, and we're
  building HIPAA-aware from day one. We only need trip structure (times, zones,
  vehicle, outcome), not names.
- *"You're students."* Correct, and that's why the analysis is free and you
  carry no risk. We're trying to learn from operators who actually run this,
  not sell you something before we've earned it.
- *"What does it cost?"* Nothing for the analysis. If we build something you'd
  pay for, founding partners get founding-partner terms. We'll be direct about
  pricing when there's something to price.

## Sending workflow (Gmail)

Generate drafts, review each, send in small human-paced batches:

1. `py -3 forge/business/outreach/generate_design_partner_emails.py --top 80`
2. For each target: find the ops / mobility / paratransit manager on LinkedIn,
   fill in `[FIRST NAME]`, fill the sender contact line once.
3. Send from your real Gmail, ~10-15/day, not a bulk blast (deliverability +
   each cold email to a finite pool of ~637 agencies is a one-shot; a sloppy
   one burns that logo permanently).
4. If the Gmail connector is authorized (claude.ai connector settings), these
   drafts can be pushed straight into Gmail as drafts for you to review and
   send - drafts, not autonomous send, on purpose. A wrong number in front of
   a director who knows their own books is unrecoverable.

## What NOT to do

- Do not auto-blast. Do not send before filling in the real contact name.
- Do not lead with the model or parameter count. Nobody buys "big transformer."
- Do not ask for raw rider PHI. De-identified trip structure only.
- Do not target the mega-metros first. Reference customer first, then them.
