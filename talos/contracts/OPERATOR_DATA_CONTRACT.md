# The operator data contract — what we need, and what each field buys

**Version 0.1 — 2026-07-26.** Generated from `talos/contracts/operator_contract.py`; if this document and that module disagree, the module is what runs and this document is the bug.

**For:** the operations director who would approve the extract, the IT lead who would run it, and the counsel who would review it. The first three sections need no schema knowledge. The field detail at the back is for whoever writes the query.

---

## 0. Read this first

**Milexium has no operator customers, no pilot, and no operator data of any
kind.** Every capability described here is Demonstrated on public and
open-standard data and on a deliberately fictional reference agency. Nothing is
Validated, which in our own status vocabulary means "tested on consented
operator data against a declared baseline". You would be the first, and this
document exists because being first should mean being told exactly what is being
asked for and why, not being handed a data request with no reasoning attached.

**This is not an agreement and cannot create one.** The data-sharing agreement --
parties, jurisdiction, liability, breach notification, termination -- is a legal
instrument for counsel on both sides. This is the technical schedule such an
agreement would reference. Sending a file does not accept terms, because there
are no terms here to accept.

---

## 1. The ask

The whole request, in one paragraph:

**nine columns you already export, six questions answerable in an
email, and two timestamps that decide whether half of this is worth doing at
all.** The nine columns are unchanged from what we have published since
ADR-0038 -- this document adds no new mandatory column, and `vehicle_ref` /
`run_ref` are an either-or, so in practice it is eight columns in
the file. The six questions cost you one reply. The two timestamps
are the part that cannot be added later, and the reason this document exists at
all.

---

## 2. The six questions

These cost you one email and they decide more than the data does. Every one of them can be answered **yes**, **no**, or **we do not record that** — and "we do not record that" is a useful answer, not a failure. It tells us what we may never claim.

**1. What date and time was this extract run?**

> *Why:* The ceiling on what can be in the file. It is also the control that catches a knowledge timestamp which is really the export time under another name -- the failure mode that would make the most important field in this contract look present and be worthless.
>
> *If we do not know:* A missing row is ambiguous between 'it did not happen' and 'it had not been entered when the extract ran', and we would have no way to detect a knowledge timestamp stamped by the export tool.

**2. What period does this extract cover, is it complete over that period, and were any trip types, contractors or funding streams excluded?**

> *Why:* Telling a quiet Sunday apart from a missing day. It is what makes any rate we report a rate rather than a count of whatever happened to be in the file.
>
> *If we do not know:* A gap in the data is indistinguishable from a gap in the service. Every per-day and per-hour figure silently inherits the shape of the extract rather than the shape of the service.

**3. Are the timestamps UTC, or local time? If local, is the UTC offset included in the string, and does it change across a daylight-saving boundary inside the export period?**

> *Why:* Reading the clock correctly. Nothing else.
>
> *If we do not know:* We assume UTC, which shifts every trip by your local offset. Every on-time number, every hour-of-day bucket and every headway would be wrong while looking perfectly well-formed -- the worst failure shape, because nothing about the output announces it.

**4. Is any vehicle in this export driven by exactly one person -- an owner-operator, a sole contractor, a single-vehicle subcontractor? How many?**

> *Why:* Knowing whether vehicle_ref is a vehicle id or a person id. It decides whether we can accept the column at all.
>
> *If we do not know:* We fail closed and withhold every vehicle-level analysis, because in a fleet where vehicle and driver are one-to-one a vehicle number is a pseudonymous person identifier no matter what the column is called. We will not guess this from the data.

**5. Was this export produced by one system or assembled from several? Name them, and say which fields came from which.**

> *Why:* Knowing whether two fields can disagree at all. One system cannot contradict itself; a booking system joined to an AVL feed joined to a dispatch console can, and does.
>
> *If we do not know:* Conflicting values have no precedence rule, so we either pick one silently -- which is the failure this whole repository is built to avoid -- or stop and ask you, mid-analysis.

**6. Does your scheduling system log the vehicle/run candidates it evaluated and rejected for a trip? If it does, are those logs retained for the export period?**

> *Why:* The difference between 'nothing else was considered' and 'we do not know what else was considered'. Those are different facts and only one of them is a finding.
>
> *If we do not know:* Backfilled decisions would carry an empty alternatives list, which reads as a claim that no alternative existed. That is a fabricated finding, and a flattering one, since it makes every decision look forced.

**And one more, but only if the export contains any denied rows.**

Can you send the denial/refusal code list with a one-line meaning per code? Expect a long tail and expect one code to mean 'other' -- tell us which one.

> *Why:* Mapping your vocabulary onto ours by agreement rather than by resemblance.
>
> *If we do not know:* Codes get bucketed by how they look, which is a fabrication dressed as a mapping. We would rather leave them unmapped and report them verbatim.

---

## 3. The two timestamps, and why they decide half of this

This is the section to read if you read only one.

When we reconstruct a decision, we need to know what your system knew at the
moment it was made. Today we would use **our** receipt time as a stand-in for
**your** knowledge time. Consider what that does:

> Your system learns at 10:30 that a vehicle is out of service. The extract runs
> at 11:00. We reconstruct the 10:45 board, and the vehicle is still on it --
> because as far as our clock is concerned, we did not know until 11:00.
>
> **But your dispatcher knew at 10:30.**

Every reconstruction built that way credits your staff with *less* information
than they actually had. And the bias has a direction: it makes your decisions
look worse than they were, and therefore makes any "an alternative assignment
would have done better" comparison look better than it is -- **in our favour**.

We are not willing to publish a comparison built on that. So the ask is a
per-row timestamp recording when the record became visible **in your system**,
distinct from when the trip happened and distinct from when the extract ran.

Two things follow, and both are uncomfortable enough to be worth stating:

1. **Many systems do not record one.** That is a completely valid answer, and it
   is the answer we most need to have before data moves, not after. If the
   answer is no, the export is still worth sending -- outcome analysis, deadhead
   measurement and demand work are all unaffected -- and decision replay is
   withdrawn from what we claim, rather than quietly approximated.
2. **It cannot be retrofitted.** A history exported without it stays without it
   forever. Adding the column next year does not repair last year.

**And a related warning about backfill.** Eight to twelve weeks arriving as a
single extract gives every row the same arrival time from our side, so every
reconstruction across that whole history shares one boundary and the
point-in-time property collapses to nothing. Without a source-side knowledge
timestamp, **backfilled data supports outcome analysis but not decision
replay.** Our validator detects exactly this and says so, rather than reporting
a capability we cannot actually deliver.

---

## 4. What we can answer, and what each answer costs

Every field in this document exists because it moves one of these from "we cannot answer that" to "we can". A field that does not appear in this table has no business being in the contract.

| We could answer | Which needs |
|---|---|
| **Outcome analysis** — How did the service actually perform -- lateness against the promised pickup, denial rate, no-show rate, demand by zone and hour? | `trip_ref`, `requested_at`, `scheduled_pickup_at`, `actual_pickup_at`, `pickup_zone`, `dropoff_zone`, `outcome`, `export_generated_at`, `coverage_window`, `timestamp_convention`, `source_systems`<br>*sharpened by* `scheduled_dropoff_at`, `outcome_known_at`, `field_authority_map` |
| **Deadhead measurement** — How much of the fleet's day was spent running empty between one trip's dropoff and the next trip's pickup? | `pickup_zone`, `dropoff_zone`, `scheduled_pickup_at`, `fleet_shape`, `one of vehicle_ref / run_ref`<br>*sharpened by* `actual_dropoff_at`, `trip_distance` |
| **Unmet-demand forecasting** — What demand did you turn away, and would a forecast have seen it coming far enough ahead to do something about it? | `requested_at`, `pickup_zone`, `outcome` |
| **Information-set replay** — What did your system know at 10:45 on a given morning -- which bookings existed, and which had not been entered yet? | `record_created_known_at`<br>*sharpened by* `knowledge_time_source` |
| **Intra-day state replay** — What did the dispatcher's board LOOK LIKE at 10:45 -- including the trips that had already been cancelled, reassigned or re-timed by then? | `record_created_known_at`, `record_updated_known_at` |
| **Counterfactual comparison** — Would a different assignment have done better than the one that was made -- judged only on what was knowable at the time? | `record_created_known_at`, `alternatives_logged`, `run_roster`<br>*sharpened by* `record_updated_known_at`, `candidate_log` |
| **Denial analysis** — Why were trips refused, in your vocabulary rather than ours -- and which of those reasons were capacity and which were policy? | `denial_code`, `denial_code_list` |

---

## 5. The fields

### Required

For a column: absent -> we decline the export rather than produce a number we cannot defend. This set is identical to the one already published in forge/knowledge/docs/OPERATOR_DATA_INTAKE.md; this contract adds no new mandatory column. For a declaration: unanswered -> we do not start, because each answer changes how the file must be read. Each is one line of an email, and 'we do not record that' is an acceptable answer to every one of them.

| Field | Where | Type | What it is |
|---|---|---|---|
| `trip_ref` | column | string, opaque to us | Your own booking or trip reference. We never resolve it back to anything. |
| `requested_at` | column | timestamp, ISO-8601, with UTC offset (2026-03-04T08:15:00-05:00) | When the trip was booked or requested. |
| `scheduled_pickup_at` | column | timestamp, ISO-8601, with UTC offset (2026-03-04T08:15:00-05:00) | The pickup time you promised or scheduled. |
| `actual_pickup_at`<br>*(outcome = served)* | column | timestamp, ISO-8601, with UTC offset (2026-03-04T08:15:00-05:00) | When the pickup actually happened. Blank for trips that were not served. |
| `pickup_zone` | column | string -- a ZONE, never an address (ZONE-NW-3, Downtown, 90210, a TAZ, a grid cell) | The geography you already schedule against, at the coarsest granularity that still means something to you. |
| `dropoff_zone` | column | string -- a ZONE, never an address | The same, for the destination. |
| `vehicle_ref`<br>*(at least one of vehicle_ref / run_ref)* | column | string, opaque to us | Vehicle or unit number, as your fleet numbers it. |
| `run_ref`<br>*(at least one of vehicle_ref / run_ref)* | column | string, opaque to us | Run, block or manifest id -- a day's chained work. |
| `outcome` | column | one of: served, no_show, denied, cancelled (your own synonyms are mapped explicitly, never guessed) | What happened to the trip. |
| `export_generated_at` | declaration | timestamp, ISO-8601, with UTC offset (2026-03-04T08:15:00-05:00) | When the extract was actually run. |
| `coverage_window` | declaration | two dates, plus a yes/no on completeness | The period the export is meant to cover, and whether it is complete over that period. |
| `timestamp_convention` | declaration | one of: UTC / local with offset / local without offset (name the zone) / mixed | How to read the timestamps in the file. |
| `fleet_shape` | declaration | yes/no, plus a count if yes | Whether any vehicle in the export is operated by exactly one person. |
| `source_systems` | declaration | a list of system names, and which fields each one produced | Which of your systems this export was assembled from. |
| `alternatives_logged` | declaration | one of: yes / no / we do not know | Whether your scheduler records the candidate assignments it rejected, not just the one it chose. |
| `denial_code_list`<br>*(the export contains any denied rows)* | declaration | the code list, with each code's meaning in your words | What your denial codes mean. |

### Required for decision replay

Absent -> the export is still worth sending and outcome analysis is unaffected, but decision replay and any counterfactual comparison are WITHDRAWN, not approximated. Cannot be retrofitted onto history already exported without it.

| Field | Where | Type | What it is |
|---|---|---|---|
| `record_created_known_at` | column | timestamp, ISO-8601, with UTC offset (2026-03-04T08:15:00-05:00) | The instant this row first became visible IN YOUR SYSTEM -- distinct from when the trip happened, and distinct from when the extract was run. |
| `record_updated_known_at` | column | timestamp, ISO-8601, with UTC offset (2026-03-04T08:15:00-05:00) | When the row was last changed in your system. |
| `knowledge_time_source`<br>*(record_created_known_at is supplied)* | declaration | a system name, plus what writes the timestamp | Which system stamps the creation timestamp, and whether it is the operational system or the reporting/export layer. |

### Helpful

Absent -> one named capability is narrowed in a way we can state precisely. Nothing else is affected.

| Field | Where | Type | What it is |
|---|---|---|---|
| `actual_dropoff_at` | column | timestamp, ISO-8601, with UTC offset (2026-03-04T08:15:00-05:00) | When the trip actually finished. |
| `scheduled_dropoff_at` | column | timestamp, ISO-8601, with UTC offset (2026-03-04T08:15:00-05:00) | The promised or scheduled dropoff time. |
| `outcome_known_at` | column | timestamp, ISO-8601, with UTC offset (2026-03-04T08:15:00-05:00) | When you learned the outcome -- particularly when a cancellation was received. |
| `denial_code` | column | your own code, verbatim -- do NOT map it onto our vocabulary | Why a trip was refused, in your system's own code. |
| `trip_distance` | column | number, miles | Distance travelled in service for the trip, as your system records it. |
| `run_roster` | table | one row per run per day: run_ref, vehicle_ref, run_start_at, run_end_at, securement_positions | Which runs operated on each day, on which vehicle, between which times, with how many wheelchair securement positions. |
| `candidate_log`<br>*(alternatives_logged = yes)* | table | one row per rejected candidate: trip_ref, candidate_vehicle_ref or candidate_run_ref, rejection code, evaluated_at | The assignments your scheduler considered and rejected. |
| `field_authority_map`<br>*(source_systems names more than one system)* | declaration | per field: which named system is authoritative | When two of your systems disagree about a field, which one is right. |

---

## 6. What we are NOT asking for, and why

A field list without this section reads as *send everything you have*, whatever the header says. Each of the following exists in your system, and each is deliberately left out.

**rider_ref (any rider identifier, including one you have already hashed)**

- *Why not:* Nothing in the analysis described here needs to link two trips to the same person. The adapter still accepts and tokenises the column because ADR-0038 shipped it as optional, but this contract does not ask for it, and the tokenisation is an unsalted hash -- a pseudonym, not anonymisation, and brute-forceable by anyone holding your client list.
- *What we give up:* Repeat-rider behaviour: no-show propensity, whether the same people are late repeatedly, subscription-trip patterns. All of it.
- *When we would ask:* Only if rider-level no-show behaviour became the agreed question, and only with a salted pseudonym generated on your side and a separate written basis for it. Not for the evaluation this contract covers.

**driver or operator identifier, even tokenised**

- *Why not:* Everything we compute attributes work to a RUN, not to a person. A driver id would buy nothing and would add a person to a dataset that otherwise contains none. Shift boundaries -- the one thing a driver id might have been used for -- are asked for on the run roster instead.
- *What we give up:* Any per-driver variation: whether lateness clusters by operator. That is a performance-management question, and it is not one we are offering to answer.
- *When we would ask:* Not currently foreseen.

**rider mobility-device, eligibility category, or trip purpose**

- *Why not:* These are health-adjacent facts about an individual. ADR-0038 refuses them and this contract does not reopen that.
- *What we give up:* This is the one omission that costs something real and it should be said plainly. Without a per-trip flag for whether an accessible vehicle was required, we can count denials coded as accessibility denials and check them against the accessible vehicles on shift (via the run roster), but we cannot measure unmet ACCESSIBLE demand directly -- only the subset your own system already labelled.
- *When we would ask:* If accessibility-denial analysis becomes the agreed question, this is the field that would make it possible, and it is a decision for your counsel rather than a request we will make by default. We are raising it here so the trade-off is visible, not to ask for it.

**fare, payment, funding source, subscription status**

- *Why not:* No capability in this contract consumes them.
- *What we give up:* Any cost or revenue statement, which we are not making.
- *When we would ask:* A cost-per-hour split (fixed versus variable) would be needed before any monetary figure could be quoted at all, and that is a separate conversation with a separate refusal attached: we do not quote a saving from a deadhead figure.

**GPS breadcrumb traces / raw AVL position streams**

- *Why not:* A breadcrumb trail is a doorstep whenever the vehicle is stopped. Zones plus timestamps answer the questions in this contract without carrying precise location.
- *What we give up:* Route-level deadhead geometry and true empty mileage.
- *When we would ask:* A per-trip odometer delta (trip_distance, above) answers the mileage question without a trace, so we ask for that instead.

**free-text notes, driver comments, dispatcher remarks**

- *Why not:* This is where personal detail actually hides, and we cannot review your free text for you. It is refused, not merely unrequested.
- *What we give up:* Whatever context a dispatcher wrote down. Genuinely a loss; taken anyway.
- *When we would ask:* Never in this form.

**live API access, database credentials, or a system integration**

- *Why not:* A file is all we want at this stage. An integration is a much larger commitment on your side and answers nothing this contract does not.
- *What we give up:* Nothing, for the evaluation described here.
- *When we would ask:* Not at evaluation stage.

---

## 7. Pseudonymisation and minimisation — what we will refuse to accept

**Rider identity must never arrive in the clear, and the gate runs before
everything else.** PII is checked ahead of all other validation -- ahead of
required-field checks, ahead of timestamp parsing, ahead of any repair of a
malformed value. A row that is both malformed and carries a rider name is
rejected on the identity ground, and the offending value is redacted from the
rejection record itself, so a rejection for rider PII never becomes a file full
of rider PII (ADR-0051).

**What we refuse to accept**, whether or not it is encrypted, zipped, or sent
"just in case it is useful": every category in the refusals table below. Refusal
means the export is set aside and you are asked to re-cut it -- not imported with
the column ignored. A column carrying a direct identifier stops the row even when
that column is blank in the sample you sent, because an all-blank column in a
two-hundred-row sample is usually a populated column in the full extract.

**An identifier does not have to be called a name to be one.** In an
owner-operator fleet -- one vehicle, one driver, one licensee -- a vehicle number
*is* a pseudonymous person identifier. `vehicle_ref` is safe for an agency's
numbered bus and unsafe for a single-vehicle subcontractor, and **nothing about
the column tells you which**. That is why the fleet-shape question is asked
directly and answered by you, rather than inferred by us from a header (ADR-0057).
If any vehicle in your export is operated by exactly one person, tokenise
`vehicle_ref` on your side before export, or send `run_ref` instead.

**Minimisation is structural, not a policy someone remembers.** Columns outside
this contract are recorded **by name only, never by value** -- an unrecognised
column in an operator export is precisely where unanticipated personal data
hides, so we decline to keep what is in it while still recording that it
existed, because silently dropping a column is its own kind of dishonesty.

**Where pseudonymisation is weak, we say so rather than implying strength.** If a
rider identifier is sent despite this document asking you not to send one, it is
replaced by an unsalted SHA-256 truncated to 24 hex characters. That is a
pseudonym, not anonymisation: over a small identifier space it is reversible by
brute force by anyone who already holds your client list, and it does not by
itself take the field outside your privacy obligations. This is stated as a
reason to omit the column, not as a reassurance.

**Honest limit on all of the above.** The automated checks are a backstop, not a
guarantee. They catch columns that announce themselves, email addresses that look
like email addresses, and zone values shaped like street addresses. A rider's
name in a column called `ref2` is not caught by anything. **This document is the
contract; the code is the seatbelt.** If you are unsure about a column, ask
before exporting rather than sending it.

### The refusals, by category

| We will not accept | Column names we see | Why |
|---|---|---|
| Personal names -- riders, carers, emergency contacts, or your own staff | `rider_name`, `client_name`, `first_name`, `last_name`, `driver_name` | Direct identifier. Nothing we compute uses a name. |
| Email addresses | `email`, `rider_email`, `contact_email` | Direct identifier, and the one that survives a column rename -- so it is also checked by value, in every cell. |
| Phone numbers | `phone`, `home_phone`, `mobile`, `cell`, `fax` | Direct identifier. |
| Street addresses | `pickup_address`, `dropoff_address`, `home_address`, `street`, `addr1`, `apt` | A pickup address is a rider's home. Zones exist precisely so this column does not have to travel. |
| National, insurance or medical identifiers | `ssn`, `national_id`, `nhs_number`, `medicaid_id`, `medicare_id`, `insurance_id`, `mrn` | Direct identifier, and in most jurisdictions a special category on top of that. |
| Dates of birth | `dob`, `date_of_birth`, `birth_date` | Quasi-identifier strong enough to re-identify on its own in combination with a zone. |
| Medical or eligibility detail | `diagnosis`, `disability_type`, `medical_condition`, `eligibility_category` | Health data about an individual. Refused regardless of any consent you may hold. |
| Free text of any kind | `notes`, `comments`, `remarks`, `driver_notes` | Unreviewable. Personal detail hides here more reliably than in the columns that announce themselves. |
| Driver-licensing and vehicle-registration identifiers | `driver_license`, `hack_license`, `medallion`, `license_plate`, `vin` | A hack licence is a person's licence, not a vehicle's, and licensee lookups are public. The 2013 NYC TLC release hashed medallion and hack licence and was de-anonymised within days because the input space is enumerable. A plate or VIN is registered to a person or a company and resolves through public and commercial lookups. |

---

## 8. The minimum viable ask

**Eight to twelve weeks, from one agency, complete over that window.**

Not five years. Not five agencies. One complete decision-to-outcome chain --
bookings arriving, assignments made, outcomes recorded, over a period long
enough to contain a holiday, a bad-weather day and a normal Tuesday -- is worth
more than five years of disconnected trip totals, because trip totals answer
"what happened" and a chain answers "what was knowable when the choice was
made". Only the second one supports anything a scheduler could act on.

Three things matter more than volume:

- **Complete over the window, not filtered.** Include denied, cancelled and
  no-show trips, the contracted-out work, and the days you would rather not show
  us. An export of served trips only makes unmet demand structurally invisible,
  and a forecast trained on it learns the shape of what you were able to serve
  rather than the shape of what was asked for. A validator finding of "every row
  in this sample has outcome=served" is treated as a defect in the extract, not
  as a perfect service record.
- **A small sample first.** Two hundred rows, fully representative, tells us and
  you far more than a full extract, because it lets both sides find the problems
  before anything of size moves. Run the validator on it -- it is the fastest way
  to turn this document into a short, specific conversation.
- **Eight weeks is a floor, not a target.** Below it, day-of-week and weather
  effects are not separable from noise, and we would be reporting the sample.

---

## 9. Check your own export before sending it

`talos/contracts/validate_operator_export.py` reads a sample export and reports,
capability by capability, what it can and cannot support -- naming the missing
field in each case. It writes nothing, sends nothing, and needs no network.

```
py -3 talos/contracts/validate_operator_export.py sample.csv
```

A typical answer looks like this, and this is the sentence this whole document
is built to make possible:

> This export supports outcome analysis and deadhead measurement. It cannot
> support decision replay, because no source-side knowledge timestamp is
> present.

It also checks the failure that a presence check would miss: a knowledge
timestamp that is **present and degenerate** -- identical on every row, or equal
to the export time, which is the signature of a value stamped by the extract
rather than recorded by the operational system. A column that looks right and
means nothing is worse than an absent one, because the resulting analysis looks
rigorous.

You are welcome to run it yourself, before anything leaves your building.

---

## 10. Limitations of this document

- This is a contract, not an integration. Nothing here connects to any scheduling system, and no operator has confirmed that any field in it exists in the shape described. Every field is a request, and several are requests we expect to be answered 'we do not record that'.
- The field list is derived from what this repository can currently consume and from what ADR-0072 had to guess about operator data. It is not derived from any real vendor export, because none has been seen.
- The validator reads a sample and reports on the sample. A sample that is clean is not evidence that the full extract is, and a column populated in two hundred rows may be null in the other two million.
- Requirement levels are our judgement about what makes a claim defensible. An operator may reasonably disagree about which fields are worth the effort, and that disagreement is a conversation this document is meant to start, not a rule it is meant to impose.
- No capability listed here has ever been exercised on operator data. Each one describes what the code in this repository is built to do, on the data described. None is a track record.

---

## 11. The field detail

For whoever writes the extract. One entry per field, in the order of the table in §5.

#### `trip_ref`

**What it is.** Your own booking or trip reference. We never resolve it back to anything.

**What it unlocks.** Every row-level statement we make. It is the handle a corrected re-send is matched on, and the key that lets a second export of the same period be reconciled with the first rather than double-counted.

**What is lost without it.** We cannot tell a re-sent correction from a duplicate trip, so a second export can only replace the first wholesale. Nothing we report can be traced back to a row you can look up.

**The question to answer.** Does every exported row carry a stable trip or booking reference that stays the same if the row is later corrected and re-sent?

#### `requested_at`

**What it is.** When the trip was booked or requested.

**What it unlocks.** Booking lead time, and the demand signal itself: demand is when people ask, not when they travel.

**What is lost without it.** A trip booked three weeks ahead and one booked at 06:00 the same morning become the same event. Lead-time distribution, same-day demand and any forecast horizon shorter than a service day all disappear.

**The question to answer.** Is the booking/request timestamp exported, and is it the time the request was made rather than the time the record was last touched?

#### `scheduled_pickup_at`

**What it is.** The pickup time you promised or scheduled.

**What it unlocks.** The promise half of on-time performance -- the thing lateness is measured against.

**What is lost without it.** Lateness is undefined. There is nothing to be late relative to, and any on-time figure would be invented.

**The question to answer.** Is the promised or scheduled pickup time exported for every trip, including trips that were later cancelled?

#### `actual_pickup_at`

*Applies when: outcome = served.*

**What it is.** When the pickup actually happened. Blank for trips that were not served.

**What it unlocks.** Realised lateness, which is the single number the whole teardown is about.

**What is lost without it.** On-time performance cannot be computed at all. We will not substitute the scheduled time for the actual one -- the gap between them is the measurement.

**The question to answer.** For served trips, is an actual pickup time recorded (AVL, driver console, or manual), and is it exported?

#### `pickup_zone`

**What it is.** The geography you already schedule against, at the coarsest granularity that still means something to you.

**What it unlocks.** Origin-destination structure, demand by area, and the spatial half of deadhead.

**What is lost without it.** Every trip becomes placeless. Demand cannot be attributed to an area, and deadhead cannot be estimated even when the vehicle chain exists.

**The question to answer.** Can pickup geography be exported as a zone, district, ZIP or grid cell rather than a street address?

**Note.** Anything coarser than an address is fine. Anything that could be a doorstep is not, and is refused -- see the refusals section.

#### `dropoff_zone`

**What it is.** The same, for the destination.

**What it unlocks.** The destination half of origin-destination structure, and the start point of the empty leg to the next trip.

**What is lost without it.** Deadhead becomes unmeasurable in space: we would know a vehicle finished one trip and started another, but not how far apart they were.

**The question to answer.** Can dropoff geography be exported as a zone rather than a street address?

#### `vehicle_ref`

*Applies when: at least one of vehicle_ref / run_ref.*

**What it is.** Vehicle or unit number, as your fleet numbers it.

**What it unlocks.** Chaining one vehicle's consecutive trips, which is the ONLY way deadhead is measurable.

**What is lost without it.** Trips cannot be put in the order one vehicle performed them, so the empty time between them does not exist as a quantity. A row naming neither vehicle nor run is unusable by the teardown.

**The question to answer.** Does each trip row name the vehicle that performed it, or the run/block it belonged to? Either is enough; both is better.

**Note.** Read the fleet-shape declaration below before exporting this. In an owner-operator fleet a vehicle id is a person id, and the question is fleet shape, not column name (ADR-0057).

#### `run_ref`

*Applies when: at least one of vehicle_ref / run_ref.*

**What it is.** Run, block or manifest id -- a day's chained work.

**What it unlocks.** The same chaining as vehicle_ref, and additionally the boundary of a shift, so 'the vehicle was idle' can be separated from 'the run had ended'.

**What is lost without it.** Idle time and off-shift time are indistinguishable, so deadhead is overstated by every hour a vehicle was legitimately not working.

**The question to answer.** Is a run, block or manifest id carried on each trip?

#### `outcome`

**What it is.** What happened to the trip.

**What it unlocks.** Separating 'happened late' from 'did not happen', and denial and no-show rates.

**What is lost without it.** A trip that was refused and a trip that was never requested look identical. Every rate we could compute would have an unknown denominator.

**The question to answer.** Is a trip status exported for every row, and can you send us your status code list so we map it explicitly rather than by resemblance?

#### `export_generated_at`

**What it is.** When the extract was actually run.

**What it unlocks.** The ceiling on what can be in the file. It is also the control that catches a knowledge timestamp which is really the export time under another name -- the failure mode that would make the most important field in this contract look present and be worthless.

**What is lost without it.** A missing row is ambiguous between 'it did not happen' and 'it had not been entered when the extract ran', and we would have no way to detect a knowledge timestamp stamped by the export tool.

**The question to answer.** What date and time was this extract run?

#### `coverage_window`

**What it is.** The period the export is meant to cover, and whether it is complete over that period.

**What it unlocks.** Telling a quiet Sunday apart from a missing day. It is what makes any rate we report a rate rather than a count of whatever happened to be in the file.

**What is lost without it.** A gap in the data is indistinguishable from a gap in the service. Every per-day and per-hour figure silently inherits the shape of the extract rather than the shape of the service.

**The question to answer.** What period does this extract cover, is it complete over that period, and were any trip types, contractors or funding streams excluded?

#### `timestamp_convention`

**What it is.** How to read the timestamps in the file.

**What it unlocks.** Reading the clock correctly. Nothing else.

**What is lost without it.** We assume UTC, which shifts every trip by your local offset. Every on-time number, every hour-of-day bucket and every headway would be wrong while looking perfectly well-formed -- the worst failure shape, because nothing about the output announces it.

**The question to answer.** Are the timestamps UTC, or local time? If local, is the UTC offset included in the string, and does it change across a daylight-saving boundary inside the export period?

#### `fleet_shape`

**What it is.** Whether any vehicle in the export is operated by exactly one person.

**What it unlocks.** Knowing whether vehicle_ref is a vehicle id or a person id. It decides whether we can accept the column at all.

**What is lost without it.** We fail closed and withhold every vehicle-level analysis, because in a fleet where vehicle and driver are one-to-one a vehicle number is a pseudonymous person identifier no matter what the column is called. We will not guess this from the data.

**The question to answer.** Is any vehicle in this export driven by exactly one person -- an owner-operator, a sole contractor, a single-vehicle subcontractor? How many?

**Note.** This is the ADR-0057 question, and it is asked as a question because it cannot be inferred from a column name. If the answer is yes, tokenise vehicle_ref before export or send run_ref instead.

#### `source_systems`

**What it is.** Which of your systems this export was assembled from.

**What it unlocks.** Knowing whether two fields can disagree at all. One system cannot contradict itself; a booking system joined to an AVL feed joined to a dispatch console can, and does.

**What is lost without it.** Conflicting values have no precedence rule, so we either pick one silently -- which is the failure this whole repository is built to avoid -- or stop and ask you, mid-analysis.

**The question to answer.** Was this export produced by one system or assembled from several? Name them, and say which fields came from which.

#### `alternatives_logged`

**What it is.** Whether your scheduler records the candidate assignments it rejected, not just the one it chose.

**What it unlocks.** The difference between 'nothing else was considered' and 'we do not know what else was considered'. Those are different facts and only one of them is a finding.

**What is lost without it.** Backfilled decisions would carry an empty alternatives list, which reads as a claim that no alternative existed. That is a fabricated finding, and a flattering one, since it makes every decision look forced.

**The question to answer.** Does your scheduling system log the vehicle/run candidates it evaluated and rejected for a trip? If it does, are those logs retained for the export period?

**Note.** A 'no' here is a completely acceptable answer and changes nothing about whether the export is worth sending. What it changes is what we are allowed to conclude.

#### `denial_code_list`

*Applies when: the export contains any denied rows.*

**What it is.** What your denial codes mean.

**What it unlocks.** Mapping your vocabulary onto ours by agreement rather than by resemblance.

**What is lost without it.** Codes get bucketed by how they look, which is a fabrication dressed as a mapping. We would rather leave them unmapped and report them verbatim.

**The question to answer.** Can you send the denial/refusal code list with a one-line meaning per code? Expect a long tail and expect one code to mean 'other' -- tell us which one.

**Note.** Required only because an export containing denied rows and no code list forces exactly the guess this contract exists to prevent. If there are no denied rows, this line does not apply.

#### `record_created_known_at`

**What it is.** The instant this row first became visible IN YOUR SYSTEM -- distinct from when the trip happened, and distinct from when the extract was run.

**What it unlocks.** Reconstructing what your system knew at any chosen instant, which is the precondition for judging a decision against the information available when it was made rather than against hindsight.

**What is lost without it.** We would use OUR receipt time as a proxy for YOUR knowledge time. If your system knew at 10:30 and exported at 11:00, our 10:45 reconstruction excludes it -- correct for us, but your dispatcher knew. Replay would then systematically credit your staff with LESS information than they had, and bias every comparison in our favour. We refuse to publish a comparison built that way, so without this field decision replay is withdrawn rather than degraded.

**The question to answer.** Does every record carry a creation/entry timestamp written by your system when the row first appeared -- and is it exportable? Many systems do not have one, and that is a valid answer.

**Note.** This cannot be retrofitted. History already exported without it stays without it, which is why it is asked before the first extract rather than after.

#### `record_updated_known_at`

**What it is.** When the row was last changed in your system.

**What it unlocks.** Replaying revisions, not just arrivals -- a trip cancelled at 09:10 was on the board until 09:10 and off it afterwards.

**What is lost without it.** Only the final state of each trip is reconstructable. A day's board can be rebuilt from bookings that arrived, but not from the cancellations, re-times and reassignments that changed it during the day -- which is most of what a dispatcher actually reacts to.

**The question to answer.** Does the record carry a last-modified timestamp? Better still: can you export a change log with one row per change rather than one row per trip?

**Note.** A change log is the ideal and a created/modified pair is the cheap approximation. If you can only give one, give created.

#### `knowledge_time_source`

*Applies when: record_created_known_at is supplied.*

**What it is.** Which system stamps the creation timestamp, and whether it is the operational system or the reporting/export layer.

**What it unlocks.** Knowing that the knowledge timestamp is real. A created_at written by a data warehouse load or by the export tool is the export time wearing a disguise, and it is indistinguishable from the real thing by inspection alone.

**What is lost without it.** We would treat an ETL load time as the dispatcher's knowledge time. That is worse than having no knowledge timestamp, because the resulting replay looks rigorous and is wrong in a direction we cannot see.

**The question to answer.** What writes that timestamp -- the booking/dispatch application at the moment of entry, or a downstream warehouse/report layer when the row was copied?

#### `actual_dropoff_at`

**What it is.** When the trip actually finished.

**What it unlocks.** Deadhead as a MEASUREMENT. The empty leg runs from one trip's dropoff to the next trip's pickup, and this is its start.

**What is lost without it.** Deadhead can only be bounded, not measured: pickup-to-pickup includes the in-service time, so every figure is an upper bound. We would report it as a bound and label it as one, which is a materially weaker statement.

**The question to answer.** Is an actual dropoff/completion time recorded and exportable for served trips?

#### `scheduled_dropoff_at`

**What it is.** The promised or scheduled dropoff time.

**What it unlocks.** The dropoff half of the promise, and a check on maximum-ride-time constraints -- one of the reasons a trip is refused.

**What is lost without it.** A trip that was picked up on time and delivered an hour late reads as on time. Ride-time constraint violations are invisible.

**The question to answer.** Is a scheduled or promised dropoff/appointment time exported?

#### `outcome_known_at`

**What it is.** When you learned the outcome -- particularly when a cancellation was received.

**What it unlocks.** Separating a cancellation received at 06:00, where the slot was recoverable, from one received at 08:14 when the vehicle was already en route. That difference is the entire operational content of a cancellation.

**What is lost without it.** All cancellations look alike, and the recoverable ones cannot be counted. Late-notice no-shows and early cancellations collapse into one rate.

**The question to answer.** Is the time a cancellation or no-show was recorded kept separately from the trip's scheduled time?

**Note.** If record_updated_known_at is supplied and maintained, this is largely implied by it. Sent separately it is more reliable, because it is the one timestamp a dispatcher enters deliberately.

#### `denial_code`

**What it is.** Why a trip was refused, in your system's own code.

**What it unlocks.** Telling capacity denials apart from policy denials. 'No accessible vehicle was free' is an operational finding; 'outside the service area' is a policy statement about the boundary, and conflating them makes the first one disappear into the second.

**What is lost without it.** `denied` is one undifferentiated bucket. We can count denials and can say nothing about them.

**The question to answer.** Does a denial or refusal carry a reason code? Send the code as it appears -- our own reason vocabulary is ours, not yours, and we will map yours to it explicitly and publish the mapping.

#### `trip_distance`

**What it is.** Distance travelled in service for the trip, as your system records it.

**What it unlocks.** Reporting deadhead in the same unit your NTD submission uses, so the figure can be checked against a number you already file rather than against one only we can compute.

**What is lost without it.** Deadhead is reported in minutes only. That is still a real measurement, but it is not directly comparable to your own reporting, and a figure nobody can cross-check is a figure nobody acts on.

**The question to answer.** Is per-trip in-service mileage recorded, and is it measured (odometer/AVL) or estimated by the scheduler?

#### `run_roster`

**What it is.** Which runs operated on each day, on which vehicle, between which times, with how many wheelchair securement positions.

**What it unlocks.** Knowing what the fleet actually was. Any 'a different assignment would have been better' statement needs the set of vehicles that existed and were on shift; and a denial for no accessible capacity can only be checked against the accessible vehicles that were actually free.

**What is lost without it.** A counterfactual can only re-sequence trips inside the runs that happened. It cannot say a different vehicle should have taken a trip, because it does not know which vehicles existed. Accessibility denials can be counted but not tested -- so we would report the count and refuse the conclusion.

**The question to answer.** Can you send a run roster for the same period: run id, vehicle, start and end time, and the number of wheelchair securement positions on that vehicle? Are securement positions fixed per vehicle, or reconfigurable during a day?

**Note.** This asks about VEHICLES, not riders. Nothing in it describes a person, and no rider mobility-device or eligibility field is requested anywhere in this contract.

#### `candidate_log`

*Applies when: alternatives_logged = yes.*

**What it is.** The assignments your scheduler considered and rejected.

**What it unlocks.** Comparing against what your system actually weighed, rather than against a set of options we reconstruct and then grade ourselves on.

**What is lost without it.** Any comparison is between your decision and our reconstruction of the option set. That is a weaker claim, and we would label it as one rather than presenting it as a replay.

**The question to answer.** If your scheduler logs rejected candidates, can those logs be exported for the same period?

#### `field_authority_map`

*Applies when: source_systems names more than one system.*

**What it is.** When two of your systems disagree about a field, which one is right.

**What it unlocks.** A precedence rule for conflicts. Our model retains both values and refuses to choose; this is the answer that lets it choose.

**What is lost without it.** Disagreements stay unresolved and are reported as conflicts rather than as values. Nothing is corrupted, but a number is missing where a number was expected, and it stops the analysis rather than biasing it.

**The question to answer.** If the AVL feed and the dispatch console disagree about an actual pickup time, which is authoritative? Does the answer differ by shift, by contractor, or by field?

**Note.** 'It depends' is the expected answer and is worth writing down as-is. A precedence rule with an honest exception list beats a clean one that nobody in dispatch believes.
