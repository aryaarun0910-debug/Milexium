# Operator data intake — what to send us, and what we do with it

**For:** the operations director who would export the file, and the counsel who
would review it before it leaves the building.

**Version:** 0.1 — 2026-07-24. Owned by `app/connect/operator_export.py`;
if this document and that adapter ever disagree, the adapter is what actually
runs and this document is the bug.

---

## 0. Read this first: two honesty statements

**Milexium has no operator customers and no operator track record.** Every
capability in this repository is **Demonstrated** — it works on public and
open-standard data (NYC TLC trip records, GTFS/GTFS-Flex/GTFS-Realtime feeds,
the TIDES specification, MTA ridership) and on a deliberately fictional
reference agency. Nothing has been **Validated**, which in our own status
vocabulary means "tested on consented operator data against a declared
baseline" (`knowledge/architecture/decisions/0001-adopt-expansion-blueprint-and-control-plane.md`,
`IMPLEMENTATION_STATUS.md`). You would be the first. If any Milexium material
you have received implies otherwise, it is wrong and we want to know.

**This document is not an agreement and does not create one.** A data-sharing
agreement is a legal instrument — parties, jurisdiction, liability, indemnity,
insurance, breach notification, sub-processing, termination, governing law. It
must be drafted and signed by the founders and your counsel. It is explicitly
**not** something this repository provides and **not** something engineering can
complete. What follows is the **technical and privacy schedule** such an
agreement would reference: the field list, the formats, the handling, the
retention and deletion mechanics. Treat it as an annex to be attached, reviewed,
and if necessary rewritten by lawyers — not as terms you can accept by sending a
file.

---

## 1. WHAT WE DO NOT WANT

Read this section before the field list. It is shorter and it matters more.

**Do not send us rider personal data of any kind.** Not encrypted, not in a
password-protected zip, not "just in case it's useful". We do not want it, we
have no use for it, and we will not accept it.

Specifically, **remove these columns before you export**:

| Do not send | Examples of column names we see |
|---|---|
| Names — riders, carers, emergency contacts, **or your own staff** | `rider_name`, `client_name`, `first_name`, `last_name`, `driver_name` |
| Email addresses | `email`, `rider_email`, `contact_email` |
| Phone numbers | `phone`, `home_phone`, `mobile`, `cell`, `fax` |
| Street addresses | `pickup_address`, `dropoff_address`, `home_address`, `street`, `addr1`, `apt` |
| National, insurance or medical identifiers | `ssn`, `national_id`, `nhs_number`, `medicaid_id`, `medicare_id`, `insurance_id`, `mrn` |
| Dates of birth | `dob`, `date_of_birth`, `birth_date` |
| Medical or eligibility detail | `diagnosis`, `disability_type`, `medical_condition`, `eligibility_category` |

We also do not want free-text notes, driver comments, or dispatcher remarks.
Those fields are where personal detail actually hides, and we cannot review
them for you.

**We fail closed, not open.** The intake adapter rejects a row that carries any
of the above rather than importing it and ignoring the column. Rejection is by
**column name**, so an all-blank `rider_name` column in your sample still stops
the import — because an all-blank column in a 200-row sample is usually a
populated column in the full extract. It also rejects on **value**: any cell
anywhere in the file that contains an email address, and any `pickup_zone` /
`dropoff_zone` that is shaped like a street address ("48 Willow Bank Road").

When a row is rejected for this reason you get back the row with the offending
values **redacted** and a message naming each offending column, e.g.:

```
rejected on ingest: the export carries direct rider/staff identifiers, which
Milexium does not accept -- rider_name (personal name); phone (phone number).
Remove these column(s) at source and re-send; see knowledge/docs/OPERATOR_DATA_INTAKE.md
('WHAT WE DO NOT WANT'). The offending values were redacted from this
quarantine record and were not retained
```

Honest limit on that check: it is a **backstop, not a guarantee**. It catches
columns that announce themselves and emails that look like emails. It cannot
detect a rider's name sitting in a column called `ref2`. The contract is this
document; the adapter is the seatbelt. If you are unsure about a column, ask us
before exporting rather than sending it.

---

## 2. The minimum field list

This is the smallest set that makes an honest teardown of your service
possible. Ten columns; six of them mandatory. Nothing here identifies a person.

| Column | Required? | What it is |
|---|---|---|
| `trip_ref` | **Yes** | Your own booking or trip reference. Opaque to us; we never resolve it back to anything. |
| `requested_at` | **Yes** | When the trip was booked/requested. |
| `scheduled_pickup_at` | **Yes** | The pickup time you promised or scheduled. |
| `actual_pickup_at` | **Yes when `outcome` is `served`**, otherwise leave blank | When the pickup actually happened. |
| `pickup_zone` | **Yes** | A **zone**, not an address. See below. |
| `dropoff_zone` | **Yes** | A **zone**, not an address. |
| `vehicle_ref` | **One of these two** | Vehicle or unit number. |
| `run_ref` | **One of these two** | Run, block, or manifest id. |
| `outcome` | **Yes** | One of `served`, `no_show`, `denied`, `cancelled`. |
| `rider_ref` | **Optional — we would rather you left it out** | Your internal opaque client id. Never a name. |

**On zones.** A zone is whatever geography you already schedule against: a
service-area code (`ZONE-NW-3`), a district name (`Downtown`), a ZIP/postal
code (`90210`), a grid cell, a TAZ. Anything coarser than an address is fine.
Anything that could be a doorstep is not.

**Why `vehicle_ref` or `run_ref` is mandatory.** Deadhead — the empty miles
between one trip's dropoff and the next trip's pickup — is measured by chaining
the trips a *single vehicle* performed in order. Without a vehicle or run
reference the trips cannot be chained and the analysis you would be doing this
for is impossible. A row naming neither is rejected.

**On `rider_ref`.** We do not need it and the analysis works without it. If you
send it, it must be your internal opaque client key, never a name. It is
replaced on arrival by `sha256(value)` truncated to 24 hex characters, and the
value you sent is not written to our database, not written to our processing
logs, and not written to the diagnostic records the import produces. The mapping
is one-way.

Honest limit, stated because your counsel will ask: an **unsalted** hash over a
small identifier space can be reversed by brute force by anyone who already
holds your client list. It is a pseudonym, not anonymisation, and it does not by
itself take the field outside the scope of your privacy obligations. That is
precisely why the column is optional and why we recommend omitting it. Without
it, repeat trips by the same rider cannot be linked to each other at all — the
placeholder we generate is derived from the trip reference, so it is different
for every trip by construction.

**What we do not ask for and do not want, even though it exists in your system:**
mobility-device or wheelchair flags, fare and payment detail, trip purpose,
subscription/standing-order status, eligibility category. If such columns are
present in the file we record only that a column of that name existed, and we do
not keep its values (see §6).

---

## 3. Accepted formats

- **CSV** — UTF-8, one header row, one trip per row. Preferred.
- **Parquet** — same columns; timestamp columns may be real timestamps rather
  than strings.

Either format, sent as a single file per extract. No database dumps, no API
credentials, no read access to your scheduling system — a file is all we want
and all we will accept at this stage.

**Timestamps.** ISO-8601, and **please include the UTC offset**:
`2026-03-04T08:15:00-05:00`. If you send `2026-03-04T08:15:00` with no offset we
treat it as UTC, which will silently shift every trip by your local offset and
quietly corrupt any on-time or headway number we produce. The import records
that assumption every time it makes it, but it is far better not to make it.

**You do not have to rename your columns.** Send your extract with whatever
headers your system produces and tell us what they mean; we configure the
mapping on our side. That is what the next section shows.

### Worked example (synthetic — no real operator data exists)

A wide vendor-style export. Your header, unchanged:

```csv
BookingNo,ClientKey,Booked On,PromisedPickup,ActualPickup,PU Zone,DO Zone,UnitNo,ManifestId,TripStatus,FareType,ProviderCode,TripMiles
BK-100244,CL-88213,2026-03-02T14:05:00-05:00,2026-03-04T08:15:00-05:00,2026-03-04T08:22:00-05:00,ZONE-NW-3,ZONE-CBD-1,UNIT-412,RUN-2026-03-04-A,Completed,ADA-fixed,SUBCON-2,6.4
```

The mapping we configure (`app/connect/operator_export.py`):

```python
column_map = {
    "BookingNo":      "trip_ref",
    "ClientKey":      "rider_ref",           # optional; better omitted
    "Booked On":      "requested_at",
    "PromisedPickup": "scheduled_pickup_at",
    "ActualPickup":   "actual_pickup_at",
    "PU Zone":        "pickup_zone",
    "DO Zone":        "dropoff_zone",
    "UnitNo":         "vehicle_ref",
    "ManifestId":     "run_ref",
    "TripStatus":     "outcome",
}
```

What that row becomes:

| Canonical field | Value |
|---|---|
| `pickup_zone` / `dropoff_zone` | `ZONE-NW-3` / `ZONE-CBD-1` |
| `times.requested_at` | `2026-03-02T19:05:00+00:00` (offset converted) |
| `times.scheduled_pickup_at` | `2026-03-04T13:15:00+00:00` |
| `times.actual_pickup_at` | `2026-03-04T13:22:00+00:00` |
| `status` | `completed` |
| `outcome.served` | `true` |
| `rider_ref` | `riderref-<24 hex chars>` — `CL-88213` is not stored |
| `vehicle_ref` / `run_ref` | `UNIT-412` / `RUN-2026-03-04-A` |

`FareType`, `ProviderCode` and `TripMiles` are outside the minimum list. We
record **that columns with those names were present** and discard their values.

A minimal export that already uses our column names, with no rider id and no
extra columns, is equally acceptable and produces the same canonical facts.
Both shapes are exercised in `evidence/conformance/property-tests/test_operator_export.py`.

### `outcome` values we accept

`served`, `no_show`, `denied`, `cancelled` — plus a published synonym list
(`completed`, `complete`, `performed`, `delivered`, `missed`, `denial`,
`refused`, `rejected`, `canceled`, `cancel`, `cancellation`), case- and
separator-insensitive. **Anything outside that list is rejected, not guessed
at.** If your system uses codes (`ST-4`, `9`) send us the code list and we add
the mapping explicitly; we will not infer it.

### What else gets rejected

Rejection means the row is set aside with a reason naming the field, so you can
fix it and re-send. It never means a row is silently dropped, and one bad row
never stops the rest of the file.

| Condition | Why we do not guess |
|---|---|
| Any column in §1, or an email in any cell, or an address-shaped zone | See §1. Fail closed. |
| A mandatory field blank | Filling it would invent a fact. |
| Neither `vehicle_ref` nor `run_ref` | The trip cannot be chained; nothing can be measured from it. |
| A timestamp we cannot parse | Guessing a date format is how you get a silently wrong analysis. |
| An `outcome` value not in the list above | Bucketing an unknown code by resemblance is a fabrication. |
| `outcome` is `served` but `actual_pickup_at` is blank | We will not substitute the scheduled time for the actual one — that is the exact number the analysis is about. |
| `scheduled_pickup_at` or `actual_pickup_at` earlier than `requested_at` | Usually two columns in different time zones. Worth you knowing about. |
| Two of your columns mapped onto the same field of ours | We will not pick one for you. |

---

## 4. What we do with the data

**Purpose limitation.** The export is used only for the specific analysis agreed
with you in writing beforehand, and for nothing else. Not for product
benchmarking, not for a case study, not for training a model we keep afterwards,
not for anything shown to anyone outside the named individuals in the agreement.

**Tenant isolation.** Your data is stored under a tenant identifier and is
isolated at the database layer, not by application code remembering to filter.
Milexium's PostgreSQL schema enables **row-level security with `FORCE`** on
every tenant-scoped table (`app/canonical/sql/rls_postgres.sql`,
`knowledge/architecture/decisions/0018-postgres-row-level-security.md`). Three properties
worth stating precisely, because "we isolate tenants" is usually a claim with
nothing behind it:

- Policies key on a session setting, and an **unset** session reads as SQL NULL,
  so the default is **deny-all**, not allow-all.
- `FORCE` is the load-bearing word. Without it the schema-owning database role
  bypasses its own policies and every isolation test passes for the wrong
  reason. With it, even our own application credential cannot read across
  tenants — and that role holds neither superuser nor `BYPASSRLS`.
- It is tested adversarially, including a test that deliberately lifts `FORCE`
  to demonstrate the boundary collapsing
  (`evidence/conformance/adversarial/test_postgres_rls_isolation.py`).

**No onward sharing.** No sub-processors. No third-party analytics. The export
is never sent to any external API, including any hosted LLM or AI service. It
is not published, not committed to source control, and not included in any demo,
screenshot, investor material, or academic write-up without your separate
written approval of the specific content.

**Where it physically sits, stated plainly.** Milexium today runs on developer
machines and a local container stack (PostgreSQL/PostGIS and a MinIO object
store, `knowledge/architecture/decisions/0032-compose-stack-and-object-storage.md`,
`0036-minio-backed-estate-raw-zone.md`). It is **not** a hosted, monitored,
certified production service. There is no SOC 2 report, no ISO 27001
certificate, no 24/7 on-call, and we will not pretend otherwise. Disk-level
encryption, access control and physical custody of those machines are the
specific controls your counsel should ask about by name, and the founders should
answer them in the agreement — not this document.

**Provenance record.** Every dataset that enters the estate carries an
acquisition manifest recording its source, the rights under which we hold it,
its checksum, the decision tasks it is permitted to support, and its retention
terms — enforced in code, and a dataset without declared rights cannot be
acquired at all (`app/estate/manifest.py`,
`knowledge/architecture/decisions/0013-governed-data-estate.md`). Manifests are committed
to source control. **The data they describe never is.**

---

## 5. Retention and deletion

**Retention period.** We hold your export for the shorter of:

- **30 days** after we deliver the agreed analysis to you, or
- **90 days** from the day we receive it,

and then delete it. If the analysis is abandoned, cancelled, or simply goes
quiet, the 90-day limit still applies and still runs out.

**Deletion on request.** You can require deletion at any time, for any reason or
none, by writing to the contact named in the agreement. No notice period, no
exit conditions, no obligation to explain. We delete within **5 working days**.

**What gets deleted.** The file you sent; every copy of it in the object store
and on local disk; every canonical row derived from it; and every intermediate
or derived artefact — feature tables, model files, cached results — computed
from it. The default is that **nothing derived from your data outlives your
data**. If a particular derived artefact needs to survive (for example, an
aggregate figure quoted in a report you approved), it must be named
individually in the agreement, and it must be an aggregate that cannot be
resolved back to a trip.

**How deletion is confirmed.** Within 5 working days of deletion we send you a
written confirmation containing:

1. the dataset identifier and the **SHA-256 of the exact file** we received, so
   you can verify we are talking about the same bytes;
2. every location it existed in — object-store bucket and key, local paths,
   database tables and the tenant identifier its rows were under;
3. the derived artefacts deleted alongside it, listed individually;
4. the date and time of deletion and the person who executed it;
5. a statement of anything retained and the agreement clause permitting it —
   normally nothing.

**The honest limit on that confirmation.** It is an attestation by a named
person, not a cryptographic proof. Nobody can prove a negative about data they
once held; any vendor who tells you otherwise is selling you something. What we
can point to concretely is that raw data is never committed to source control
(only its manifest is), so there is no version-control history quietly holding a
copy after deletion. Backup and disk-remanence handling is a control question
for the agreement, not a claim to make here.

---

## 6. Diagnostics we keep, and what is in them

Every import produces two kinds of record, and it is worth knowing exactly what
they contain because they outlive the row they describe until deletion.

**Rejected rows** are kept so you can fix and re-send them. They preserve your
row as sent — except that when a row was rejected for carrying a direct
identifier, **that value is replaced with a redaction marker before the record
is written**. A rejection for rider PII does not become a file full of rider PII.

**Semantic-loss notes** record every source column that did not map onto a
canonical field, so nothing is ever silently discarded
(`knowledge/architecture/decisions/0007-connect-adapter-contract-v0-1.md`). For a column
outside the minimum field list we record **the column name only and never its
value** — an unrecognised column in an operator export is exactly where
unanticipated personal data hides, so we decline to keep what is in it. These
notes also record, on every single row, what we could *not* determine: that we
never observed the trip's lifecycle transitions, that we cannot judge on-time
performance because the on-time window is your policy and not a fact in the
file, and that our canonical model has no home for a vehicle assignment. Those
are limitations of the analysis and you should see them.

---

## 7. What we still need from you (not code)

Engineering can go no further than this page. Before any file moves, the
following are founder/legal tasks:

- [ ] **A signed data-sharing agreement** — parties, jurisdiction, permitted
      purpose, liability, insurance, breach notification, sub-processing,
      termination, governing law. This document is at most an annex to it.
- [ ] **The contracting entity, and whether one exists yet.** Your counsel will
      ask who the counterparty is. Answer it truthfully before asking for data.
- [ ] **Named individuals** who will have access, and the commitment that the
      list does not grow without your written approval.
- [ ] **A privacy assessment on your side.** Whether a DPIA/PIA is required, and
      whether an FTA, state, or funder condition attaches to the data, is your
      determination to make — we are not qualified to make it for you and will
      not offer an opinion.
- [ ] **Secure transfer.** How the file actually gets to us, agreed in writing
      before it is sent. Not unencrypted email.
- [ ] **A named contact on each side** for deletion requests and for questions.

---

## 8. Status of this document

**Exists (v0.1).** The adapter it describes is implemented and tested against
two structurally different **synthetic** exports; no real operator export has
ever been received or processed. The field list, rejection rules, and
diagnostics described above are enforced in code
(`app/connect/operator_export.py`,
`evidence/conformance/property-tests/test_operator_export.py`). The retention periods,
deletion mechanics, purpose limitation, and access list described in §4 and §5
are **stated commitments, not implemented automation** — there is no scheduled
deletion job and no access-control system behind them today. They are what an
agreement would bind us to and what a person would carry out.

Saying which half is code and which half is a promise is the point.
