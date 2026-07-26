# Public evidence scout — regulatory findings, litigation, and research literature

Research scouting pass, 2026-07-26. **Nothing was acquired, downloaded to the
repository, or registered for in producing this document.** Three PDFs were read
through a transient buffer to characterise their contents and were deleted; no
bytes entered the estate. This is a plan and a citation list for the founder to
act on.

Companion to `data/acquired/ACQUISITION_PLAN.md` and
`data/acquired/US_OPEN_DATA_SURVEY.md`. Those two asked *what operational
telemetry can Milexium hold.* This one asks a different question:

> **Is there third-party, public, citable evidence that capacity denials are a
> real, recurring, named problem at named US transit agencies — and does any of
> it carry agency-level numbers?**

The answer is **yes, on both counts**, from two independent federal regulators
and from the federal courts. That is the headline. §1 states it; §§2–5 establish
it; §7 gives the rights verdicts; §9 is the separate literature deliverable.

---

## 0. Read this first — the access constraint that shaped this pass

**Every `dot.gov` host refused this client at the CDN.** `www.transit.dot.gov`,
`www.fta.dot.gov`, `www.transportation.gov`, `rosap.ntl.bts.gov` and `www.gao.gov`
all return `403 Forbidden` from `AkamaiGHost` — an edge block, not a missing
page, and not a WAF rule a different user-agent defeats (tested). The
`ACQUISITION_PLAN` hit the same wall on `transit.dot.gov` and `bts.gov` and
recorded it as a verification failure. It is almost certainly geo-blocking of
non-US traffic.

This matters for reading the rest of this document:

- FTA primary pages were read **through the Internet Archive**
  (`web.archive.org`), which is reachable. Snapshot dates are given. Where a
  figure comes from an archived capture rather than the live page, it says so.
- `justice.gov`, `ada.gov`, `archive.ada.gov`, `courtlistener.com`,
  `onlinepubs.trb.org`, `nationalacademies.org` and `data.transportation.gov`
  are **directly reachable** and were read live.
- **The founder, opening these pages in a browser, may see them fine.** Nothing
  here should be read as "FTA has taken this down." Where I could not read
  something at all, it is marked *unverified* rather than guessed at.

---

## 1. The three findings, ranked by what they unlock

| # | Source | What it unlocks | Rights | Effort |
|---|---|---|---|---|
| 1 | **FTA ADA Paratransit Compliance Reviews** — 84 reports, 2000–2021 | Regulator-measured denial, OTP, hold-time and travel-time data at ~78 named agencies | US federal work, **no explicit label** | medium |
| 2 | **DOJ ADA enforcement** — findings letters, settlements, consent decrees, ~2010–2023 | Same class of evidence, **more recent**, and with numeric remedies | US federal work, **no explicit label** | low |
| 3 | **Federal court opinions** in ADA paratransit class actions | Denial rates entered as *evidence and tested by a court* | Public domain (judicial edicts) | low |

These are one family of evidence, not three unrelated sources: all three apply
the same regulation — **49 CFR § 37.131(f)** — and the same operational
definitions. Acquiring one and not the others would be a mistake.

### The single most valuable datum found

FTA's 2020 compliance review of **Memphis Area Transit Authority** records both
what the operator reported and what FTA measured:

> "In material sent to the review team prior to the site visit, MATA reported a
> denial rate of **2.3 percent** during FY 2019. During the first 6 months of
> FY 2020, the reported denial rate was **1.7 percent**."

> "Over the course of these periods, team members observed callers request a
> total of 74 trips. Of these requests, **20 resulted in denials** … The denial
> rate for this sample was **27 percent** (20 of 74)."

> "…callers requested 46 MATAplus trips. Of these, **17 trip requests were
> denied**. The denial rate for this sample was **37 percent**."

An order of magnitude, at a named agency, documented by the regulator. The same
report shows FTA rejecting MATA's *definition* of a missed trip as incomplete.

SEPTA's 2018 review shows the mechanism by which the gap opens:

> "SEPTA's pre-visit information included the statement, 'SEPTA has a
> **zero-denial policy**. All trips are negotiated to a time within one hour of
> the request time.'" … "Two of the 81 trips reserved during review team
> observations violated the one-hour trip negotiation requirement … such
> instances constitute trip denials." … "**SEPTA does not track** instances when
> the offered times lead to non-compliant trip negotiations."

**Why this is the thing Milexium could not otherwise obtain.** It is
third-party, adversarial, regulator-issued evidence that (a) capacity denials
are real and recurring, (b) operator-reported denial counts are systematically
understated, and (c) the understatement happens through *definitional* choices
at the point of scheduling — exactly the decision Milexium records. An auditable
denial record is not a nice-to-have if the alternative is a self-reported number
that is wrong by 10×. **This is the argument for the product, made by the
regulator, about named operators, in writing.**

---

## 2. FTA ADA Paratransit Compliance Reviews — the priority

### They exist, and here is the exact inventory

**Index:** <https://www.transit.dot.gov/regulations-and-guidance/civil-rights-ada/ada-compliance-review-final-reports>
(403 to this client; read via Wayback capture `20260206170938`, i.e. 2026-02-06).

The page has two sections, and I enumerated every row:

| Section | Count | Span |
|---|---|---|
| **Paratransit** | **84 reports** | Aug 2000 – Mar 2021 |
| Fixed-Route Operations (Lifts / Stop Announcements) | 33 reports | Nov 2000 – Feb 2017 |
| **Total** | **117** | |

Roughly **78 distinct agencies** in the paratransit set; ~14 appear twice
(SEPTA, WMATA, MARTA, MATA Memphis, Maryland MTA, PVTA, MCTS, TARTA, Transpo,
Guam, ABQ Ride, Sun Metro, BJCTA, Hampton Roads). Repeat reviews at different
dates are a **within-agency before/after pair** — unusually valuable.

Named agencies include: SEPTA, Access Services (LA), Pace, WMATA, NYC Transit,
LACMTA, MBTA, TriMet, RTD Denver, Metropolitan Council, Houston METRO, MARTA,
CapMetro, VIA, Maryland MTA, MTS San Diego, Pierce Transit, IndyGo, Milwaukee
County, Memphis, Honolulu DTS, Fresno FAX, Riverside, Hillsborough (Tampa), Sun
Metro, Cleveland RTA, Central Ohio, KCATA, Delaware DART, Connecticut DOT, and
~50 small and mid-size systems.

**Format.** Recent reports (≈2015 onward) are PDF; older ones (2000–2005) are
Microsoft Word `.doc`. Direct file paths are stable and predictable, e.g.:
- `…/files/docs/regulations-and-guidance/civil-rights-ada/118291/septa-final-ada-paratransit-report-2018.pdf`
- `…/files/2020-12/memphis-area-transit-authority-final-ada-paratransit-report-2020.pdf`
- `…/files/docs/Cleveland_Final_Report_020802.doc`

Some entries carry a separate **Transmittal Letter** PDF (Sun Metro, Maryland
MTA). Typical size 1.5–10 MB; Memphis 2020 is 10.3 MB, 7 chapters plus
appendices.

### What is actually in them — verified by reading two in full

I read the **SEPTA September 2018** and **Memphis MATA December 2020** reports
end to end. Both follow an identical template:

1. Executive Summary
2. General Information / Jurisdiction and Authorities
3. Purpose and Objectives
4. Introduction to the agency (organisational structure, contractors)
5. Scope and **Methodology** (including sampling design)
6. **Findings and Advisory Comments** — §§6.1–6.12, each keyed to a CFR cite
7. **Summary Table of Compliance Review Findings**
8. Appendices — including the **agency's formal written response**

§6.4 is the capacity-constraints section, subdivided exactly as the regulation
is:

- No Restrictions on the Number of Trips Provided
- No Waiting List for Access to the Service
- **No Substantial Numbers of Significantly Untimely Pickups**
- **No Substantial Numbers of Trip Denials or Missed Trips**
- **No Substantial Numbers of Trips With Excessive Trip Lengths**
- No Operational Patterns or Practices Limiting Availability

**They contain real tabulated operational data.** Memphis 2020 alone has:

| Table | Content |
|---|---|
| 4.1 | MATAplus ADA paratransit ridership (FY series) |
| 6.1 | 2019 eligibility determination statistics and outcomes |
| 6.2 | Eligibility processing times, 32-applicant sample |
| 6.3 | **On-time pickup performance, 6,572 completed trips, Dec 8–21 2019** |
| 6.4 | **Missed trips by FY: scheduled trips, missed trips, per-1,000 rate** |
| 6.5 | Paratransit travel times vs comparable fixed-route trips |
| 6.6 | **Telephone hold time analysis, Dec 8–21 2019** |
| 6.7 | On-time **drop-off** performance, Nov 3–9 2019 |

SEPTA 2018 Table 6.5 tabulates on-time pickup performance for **12,755
Philadelphia ADA trips, week of May 6–12 2018**, bucketed `>30 min late /
16–30 / 1–15 / in-window (-10/+20) / 1–15 early / 16–30 early / >30 early`,
then Table 6.6 breaks late and very-late pickups **down by carrier** (OTP range
87.6% MV Contract 1 → 80.2% First Transit).

### Structured or narrative? — **Both, and that is the opportunity**

The prose is narrative. But every report ends with a **Summary Table of
Compliance Review Findings** with a fixed schema:

`Item | Part 27/37/38 Requirement | CFR Reference | Site Visit Finding (deficiency / no deficiency / advisory comment) | Finding(s) of Deficiency | Response Days/Date`

That is a parseable, cross-agency schema: **agency × review date × CFR
requirement × deficiency status × corrective-action deadline.** Across 84
reports and ~25 requirement rows each that is on the order of **2,000 structured
regulator judgements**, plus the metric tables underneath them.

**No such structured corpus appears to exist publicly.** Building it would be an
original, citable, rights-clean asset — and it is the natural evidence base
behind a denial record.

### The gift hiding in the regulation

The reports quote FTA's operational definition of a denial verbatim:

> "A denial occurs whenever a transit agency is unable to provide a trip on a
> next-day basis as requested by an eligible passenger … Under 49 CFR
> § 37.131(b), transit agencies may negotiate pickup times with a passenger, but
> cannot require the passenger to schedule a trip to begin more than one hour
> before or after his or her desired departure time. **If the trip cannot be
> arranged within this timeframe, a denial has occurred whether or not the
> passenger accepts** a departure time of more than one hour earlier or later.
> In addition, **when a denied trip makes a subsequent requested trip
> impossible** … **two trips have been denied**."

Milexium's denial taxonomy should be aligned to this and should cite it. Two
consequences fall straight out and are non-obvious:

1. **An accepted trip can still be a denial.** Denial is a property of the
   *offer relative to the request*, not of the rider's acceptance. Any
   implementation that logs denials only when a rider walks away is undercounting
   by construction — which is precisely the SEPTA finding.
2. **Denials propagate.** A denied outbound leg denies the return. Denials are
   not independent events, so counting them as independent understates them.

Neither of these is inferable from operator telemetry alone. Both are free.

### Rights verdict: **US FEDERAL WORK — PUBLIC DOMAIN ON THE STATUTORY BASIS, NO EXPLICIT PER-DOCUMENT LABEL**

- **Basis:** <https://www.usa.gov/government-copyright> — a US government work is
  "something created by a U.S. government officer or employee as part of their
  official duties" and such works are "not subject to copyright protection."
  Statutory basis 17 U.S.C. § 105.
- **What the page also says, and it matters here:** federal pages "may include
  protected intellectual property used with the right holder's permission"; you
  "cannot use federal government trademarks or federal government agency logos
  without permission"; and material must not "imply endorsement by a government
  agency."
- **Honest caveat — read this before declaring.** I found **no licence or
  terms-of-use statement on the compliance-review pages or in the report PDFs
  themselves.** This is the *same weaker class of declaration* the
  `ACQUISITION_PLAN` recorded for LEHD LODES8 — statutory inference, not a
  machine-readable label like `USGOV_WORKS` on `data.transportation.gov`. The
  manifest must say "US federal work, 17 U.S.C. § 105, no explicit label" and
  **not** "public domain, declared."
- **Second caveat, specific to these documents.** The reviews were conducted
  with contractor support. `usa.gov`'s definition turns on *officer or employee*.
  These are issued as FTA's own findings under FTA letterhead and signature,
  which is the strong reading — but it is an inference, and it is not one I can
  verify from a published statement. Flag it in the manifest; do not paper over
  it.
- **Cannot use FTA's logo or imply FTA endorsement.** Relevant because this
  material is commercially persuasive. Cite it; never brand with it.

**Verdict: acquirable and citable, commercial use permitted on the statutory
basis, with a weaker rights declaration than the estate's NTD holdings and two
caveats recorded.**

### One more thing worth knowing

**No paratransit compliance review has been issued since March 2021** (Gwinnett
County Transit), as of the 2026-02-06 capture. Twenty-one years of reviews then
five years of silence. Read two ways: the corpus is **closed and completable**
(good — a finite, bounded acquisition), and **the most recent regulatory
evidence is now DOJ's, not FTA's** (see §3). Do not present this corpus as
current-state evidence about any agency's operations today.

---

## 3. DOJ ADA enforcement — the recent stream, and easier to get

FTA stopped in 2021; **DOJ did not.** This is a distinct, more recent, and
directly readable body of the same evidence — and `justice.gov` and `ada.gov`
are **not blocked**.

Actions identified involving paratransit capacity constraints:

| Agency | Action | Date |
|---|---|---|
| Maryland Transit Administration | Letter of Findings | 2023-07-13 |
| City and County of Honolulu | Settlement Agreement | 2023-01-24 |
| New Jersey Transit | Settlement Agreement | 2022-12-22 |
| **New York City Transit (Access-A-Ride)** | **Letter of Findings** | **2022-10-17** |
| County of Hawaii Mass Transit | Settlement Agreement | 2021-08-23 |
| County of Muskegon, MI | Settlement Agreement | 2021-07-01 |
| Virgin Islands Dept. of Public Works | Settlement | 2014-11-14 |
| City of Jackson, MS (JTRAN) | Consent Decree | 2010-03-30 |
| City of Detroit (DDOT) — *Dilworth* | Consent Decree | 2005-11-03 |

*(Dates from FTA's ADA Compliance page as surfaced in search; the individual DOJ
documents below were read directly. Treat the list as **substantially but not
exhaustively verified** — I confirmed the NYCTA and Detroit documents by reading
them, and the Jackson and SEPTA items via DOJ/press sources.)*

### Verified by reading: DOJ Letter of Findings, NYCTA Access-A-Ride

**URL:** <https://www.justice.gov/crt/media/1259391/dl> (7-page PDF, read live)
**Case page:** <https://www.justice.gov/crt/case/new-york-city-transit-authoritys-access-ride-program>
Issued by the **US Attorney, SDNY**, 2022-10-17.

Verbatim numeric findings:

> "An analysis of drop-off performance for a sample week revealed that for all
> AAR trips with a requested drop-off time, **13.9 percent were late** according
> to FTA's standard … By borough, this ranged from **10.5 percent (Queens) to
> 16.4 percent (Manhattan)**. Excluding drop-offs that were one to five minutes
> late, consistent with NYCTA's approach, **9.9 percent** of drop-offs were more
> than five minutes late."

> "**38.7 percent of drop-offs occurred more than 30 minutes prior to the
> requested appointment time**, another indication of a capacity constraint."

> "…we found paratransit travel times to be excessive for **78% of trips
> originating in Brooklyn, 91% … Manhattan, and 72% … Queens**."

> "…among the **13 private carriers**, the proportion of trips that exceeded the
> NYCTA standard for travel time ranged from **2.20 percent to 5.96 percent**."

Note what that last pair does. Measured against **NYCTA's own standard**, carrier
performance looks fine (2–6% exceedance). Measured against the **regulator's
standard**, 72–91% of trips are excessive. Same trips, same week — the entire
difference is the definition. **That is the case for an independent evidence
layer, stated in a federal enforcement letter.** It is also a warning: any
metric Milexium computes must name the standard it is computed against.

### Verified by reading: DOJ amicus brief, *Liberty Resources v. SEPTA*

**URL:** <https://archive.ada.gov/briefs/septabr.htm> (read live), 2000-12-15.

> "SEPTA denied **5%** of the paratransit demand (non-standing) service requests,
> **averaging 74 denials per day**" — monthly range **3.2%–10.6%**
> Next-day: **13.4%** of requests over thirteen months, **~30 denials/day**, monthly range **8.9%–23.7%**
> Weekend: **9.1%**, **~75 denials per weekend day**, monthly range **2.6%–19.8%**
> Peak-hour: **6.4%**, **~66 denials/day**, monthly range **4.7%–11.4%**
> Fleet: "SEPTA uses only **278 of its 371** paratransit vehicles" on an average weekday, with "**6 to 30** of the remaining vehicles routinely out of service"

**This is a denial *time series* with monthly variation, segmented by service
type, plus the fleet-availability figure that explains it.** It is the closest
thing to an agency-level denial panel I found anywhere in the public record.

### Verified by reading: *Dilworth v. City of Detroit* consent decree

**URL:** <https://archive.ada.gov/detroittransit05.htm>, signed 2005-11-03,
No. 2:04-cv-73152 (E.D. Mich.).

Fixed-route lift compliance rather than paratransit denials, so less directly on
point — but it establishes the **shape of the remedy**: numeric service
obligations ("Alternative Transportation will arrive within 30 minutes";
customer "will not experience a delay of more than 3 minutes in reaching an
operator"; lift out of service "no more than three service days") plus **six
mandated reporting periods, May 2006 – Sept 2008, with database tracking of
maintenance, complaints and requests.**

That pattern recurs: consent decrees **manufacture operational datasets** that
would not otherwise exist, and put numeric thresholds on them. Two examples
found via search and **not yet read in the primary source (unverified)**:

- ***Liberty Resources v. SEPTA*** — SEPTA ordered to permit **no more than five
  trip denials daily**, with **fines for excess denials** and a voucher backup.
- **City of Jackson, MS (JTRAN)** — **no more than 10 trip denials in a month**,
  a denial defined as inability to provide the trip *or* an offer differing by
  **more than 60 minutes** from the request.

If those hold, they are procurement-grade: a federal court has priced a denial.

### Rights verdict: **US FEDERAL WORK — same basis, same caveats as §2**

Same statutory basis (<https://www.usa.gov/government-copyright>). DOJ findings
letters and briefs are authored by US Attorneys — **officers and employees** —
so the contractor caveat in §2 does **not** apply here. This is the *cleaner* of
the two federal streams on rights, as well as the more recent on content.

`archive.ada.gov` is an **archival** host: content is retained but no longer
updated; current material lives at `ada.gov`. No copyright statement appears on
either the Detroit decree page or the SEPTA brief — consistent with, but not
proof of, public-domain status.

---

## 4. ADA litigation and court records

### What is realistically accessible for free — verified

**CourtListener / RECAP (Free Law Project)** — <https://www.courtlistener.com/>
Reachable and functional. A search for `"paratransit" "capacity constraint"`
across opinions returned the canonical line of cases:

| Case | Court | Citation |
|---|---|---|
| *Anderson v. Rochester-Genesee Regional Transportation Authority* | 2d Cir. 2003 | 337 F.3d 201 |
| *Anderson v. RGRTA* (class cert.) | W.D.N.Y. 2001 | 206 F.R.D. 56 |
| *Liberty Resources, Inc. v. SEPTA* | E.D. Pa. 2001 | 155 F. Supp. 2d 242 |
| *Disability Rights Council v. WMATA* | D.D.C. 2006 | 239 F.R.D. 9 |

Also identified but not yet traced to a docket: *Richman v. SEPTA* (1994),
*Raver v. Capital Area Transit* (1994), and the ACLU/Disability Rights class
action against LA County transit.

**PACER costs money and is therefore out**, per the hard constraint. The
question was whether the free route is sufficient. It largely is:

- **Opinions** — free and complete on CourtListener.
- **Dockets and filed documents** — free *where a RECAP user has already
  purchased and contributed them*. Coverage is good for high-profile civil-rights
  litigation and patchy elsewhere. **Not guaranteed for any specific case.**
- **Bulk data** — CourtListener publishes CSV bulk exports (courts, dockets,
  opinion clusters, citation map, judges, oral arguments) from an **AWS S3
  bucket, no authentication**:
  `https://com-courtlistener-storage.s3-us-west-2.amazonaws.com/list.html?prefix=bulk-data/`
  Docs: <https://wiki.free.law/c/courtlistener/help/api/bulk-data/bulk-legal-data>

  ⚠️ **The 2 TB case-law embeddings dataset is explicitly noted as incurring
  ~$200 in AWS fees. That is a paid service. Excluded — do not touch it.** The
  ordinary CSV bulk files are not in that category.

### Does litigation contain operational data? — **Yes, and it is the best-quality data in this review**

*Liberty Resources* is the proof: month-by-month denial rates segmented by
next-day / weekend / peak-hour, denials per day, and fleet availability — data
that was **entered as evidence, contested by the defendant, and adjudicated by a
court**. The court's framing is itself useful to Milexium:

> …in finding a pattern or practice violation, trip denials deserve heightened
> scrutiny; the focus is not on the percentage of rides provided but "the number
> of rides that SEPTA failed to provide and the reasons for that failure."
> *(via search summary of the opinion — **the opinion text itself I could not
> read**; see §10.)*

"The number of rides not provided **and the reasons for that failure**" is,
almost word for word, what Milexium's denial record is for. If that quotation
survives checking against the opinion, it is the best single sentence in this
document for a pitch. **Verify it before using it.**

### Rights verdict: **PUBLIC DOMAIN FOR THE OPINIONS; MIXED FOR THE HOSTS**

- **Judicial opinions and court filings** carry no copyright — the government
  edicts doctrine, affirmed in *Georgia v. Public.Resource.Org*, 590 U.S. 255
  (2020). Federal court documents are US government works besides.
- **CourtListener bulk data** is "free of copyright restrictions, marked with
  the **Public Domain Mark**", no commercial-use restriction stated —
  <https://wiki.free.law/c/courtlistener/help/api/bulk-data/bulk-legal-data>
  (read live).
- ⚠️ **Unverified and potentially important.** A search snippet indicates
  CourtListener *site content* is "licensed under a **Creative Commons BY-ND**
  international 4.0 license, except where indicated." **BY-ND forbids
  derivatives**, which would matter if we processed their pages rather than the
  underlying documents. I could **not** read
  <https://www.courtlistener.com/terms/> — it returns a bot challenge to both
  WebFetch and a browser-headers request. **Do not rely on my characterisation.
  Open that page in a browser and record it verbatim before acquiring anything
  from CourtListener.** The safe reading: the *documents* are public domain, the
  *site's own editorial layer* may not be — so take documents, not pages.
- **Justia** (<https://law.justia.com/>) mirrors the same opinions and surfaced
  in search with the *Liberty Resources* figures, but blocks automated reading
  (403 / challenge). Site terms **unverified**. Treat as a human-reading
  convenience, not an acquisition target.

---

## 5. TCRP publications

Free to read; **not free to reuse.** That distinction is the whole rights story
here and it is the opposite of the federal sources above.

### Directly relevant reports — numbers and titles verified against TRB's index

<https://www.trb.org/Publications/PubsTCRPSynthesisReports.aspx> (read live)

| Report | Title | Date | Why it matters |
|---|---|---|---|
| **Synthesis 174** | Paratransit Fleet Configurations | 2024-03-01 | **fleet mix** — the brief's target |
| **Synthesis 168** | **Continuous Dynamic Optimization: Impacts on ADA Paratransit Services** | 2023-02-16 | **scheduling software evaluation** — closest thing to a peer review of what Milexium competes with |
| **Synthesis 161** | ADA Paratransit and Other Demand-Responsive Transportation Services in Small to Midsized Transit Agencies | 2022-02-23 | small-operator segment |
| Synthesis 165 | Customer Education and Awareness of On-Demand Mobility | 2023-01-19 | peripheral |
| Synthesis 163 | Considering the Unbanked in Cashless Fare Payment for Bus/Demand-Response | 2022-05-19 | peripheral |
| **Synthesis 135** | ADA Paratransit Service Models | 2018 | 258 pp; DOI 10.17226/25092; has **Appendix D — Survey Responses by Question** |
| **Report 124** | Guidebook for Measuring, Assessing, and Improving Performance of Demand-Response Transportation | 2008 | Ch. 6 "Assessing Performance Data from Representative Systems" |
| **Report 88** | A Guidebook for Developing a Transit Performance-Measurement System | 2003 | **direct free PDF verified**, see below |

### TCRP Synthesis 174 — the one with a personal connection

<https://nap.nationalacademies.org/catalog/27615/paratransit-fleet-configurations>
(catalog now redirects to `nationalacademies.org`; front matter read live)

- Published **2024**; ISBN **978-0-309-70942-2**; DOI **10.17226/27615**
- Sponsored by **FTA in cooperation with APTA**; research by **Texas A&M
  Transportation Institute**
- **Topic SB-38 panel: Christian T. Kent (Chair)**, Sara Sanford, Ross Silvers,
  Miles Turpin, Jay Washburn, Justus Welker, Robert Earl Williams, Marilyn Yokley
- **Contains an exploratory survey of 37 transit providers**, fleets ranging up
  to **700 vehicles**, plus **five case examples** — Portland, San Diego,
  Pinellas County, Broward County, Ann Arbor
- Front matter states the first wave of fleet reconfiguration delivered "lower
  operating costs and greater service delivery flexibility" from mixing in
  smaller vehicles and sedans

*The panel roster is worth cross-checking against the consultant we are
corresponding with — I have not assumed which member that is.*

### Which contain aggregated operator data rather than narrative

**Verified:** Synthesis 174 — 37-provider survey + 5 case examples.
**Strongly indicated but content unread (see §10):**
- Synthesis 135 — has a dedicated **"Appendix D — Survey Responses by
  Question"** and **Chapter 5 — Survey Analysis Summary**; respondent count
  **unverified**.
- Synthesis 168 — Chapter 2 is a survey, Chapter 3 is "Transit Agency Profiles"
  (pp. 33–64); respondent count and whether it reports before/after productivity
  or OTP metrics **unverified**.
- Report 124 — Chapter 6 "Assessing Performance Data from Representative
  Systems", pp. 49–76.

**I could not read the survey tables in any of these.** The NAP online reader
serves scanned page images, not text, so automated reading returns nothing. This
is the largest content gap in this pass and it is a five-minute fix for a human
with a browser.

### Rights verdict: **COPYRIGHTED BY THE NATIONAL ACADEMY OF SCIENCES — NOT PUBLIC DOMAIN, AND NOT LICENSED FOR COMMERCIAL REUSE**

Verbatim from the Synthesis 174 front matter:

> "**© 2024 by the National Academy of Sciences.** National Academies of
> Sciences, Engineering, and Medicine and the graphical logo are trademarks of
> the National Academy of Sciences. **All rights reserved.**"

And the standard Cooperative Research Programs notice:

> "Cooperative Research Programs grants permission to reproduce material in this
> publication **for classroom and not-for-profit purposes**" with acknowledgment.

**This is a hard boundary and it cuts against the intuition that
federally-sponsored research is public domain.** TCRP is funded by FTA but
published by NAS, and NAS holds the copyright. The grant of permission is
expressly limited to **classroom and not-for-profit** use. **Milexium is
commercial. We do not have that permission.**

What that does and does not forbid:

- ❌ **Do not** reproduce TCRP text, tables, or figures in Milexium product,
  marketing, or documentation.
- ❌ **Do not** ingest TCRP tables into the estate as a dataset.
- ✅ **Do** read them, cite them, and rely on the underlying *facts*. Facts and
  data are not copyrightable (*Feist*, 499 U.S. 340) — a number is not owned,
  the expression and the compilation are.
- ✅ **Do** ask. Permissions requests to NAS are routine and often granted; the
  same is true of a licence to reuse a specific figure. **That is an email, not
  a lawyer** — and unlike everything else in this document it has a named,
  reachable counterparty.

### Free full text — precisely what is and is not free

- ✅ **Verified direct PDF, no account, no email:**
  `https://onlinepubs.trb.org/onlinepubs/tcrp/tcrp_rpt_88.pdf`
  (4,113,008 bytes, `application/pdf`). Older TCRP reports are served this way.
- ⚠️ **Newer reports redirect to NAP.** `tcrp_rpt_124.pdf`, `tcrp_syn_135.pdf`
  and `tcrp_syn_174.pdf` on `onlinepubs.trb.org` all return **HTML, not PDF** —
  they bounce to the NAP catalog.
- ⚠️ **NAP offers "Download as a Guest"** — no account creation, but **an email
  address is required** and terms must be accepted. **Under this brief's
  "register for nothing" rule I did not use it.** It is a legitimate founder
  action; it is not a scout action. There is no payment at any step.

---

## 6. Anything else genuinely public and unexploited

### 6.1 NTD tables the estate does not currently use

Read from FTA's NTD data page via Wayback (2025 capture). The estate holds the
annual agency file, the monthly ridership panel, and the by-mode service/opex
series. **Not currently used, and relevant:**

| Product | Why it is worth having |
|---|---|
| **Annual Database Contractual Relationship** | Which operators purchase DR service, from whom, and under what contract type. The `ACQUISITION_PLAN` treats purchased transportation as a cost line; this makes it a **structural variable**. Directly relevant to a fleet/contract-mix model, and to the SEPTA/NYCTA carrier-level findings above. |
| **Monthly Modal Time Series (Safety and Service)** | Monthly **service** data by mode — VRM/VRH at monthly granularity. The estate has monthly *ridership* and annual *service*. This is the missing cell. |
| **Annual Database Facility Inventory** | Maintenance and operating facilities. **Garage location is the missing input for deadhead reconstruction** — Program A's `DeadheadSegment` needs a pull-out origin. Whether this file carries coordinates or only counts is **unverified**. |
| TS2.2 — Service Data and Operating Expenses Time Series **by System** | System-level companion to the by-mode series already held. |
| TS4.1 — Asset Inventory Time Series | Fleet age and count over time — a fleet-mix prior, and the NTD-side complement to TCRP Synthesis 174. |
| Annual Database Agency Mode Service | Agency×mode service detail. |

**Rights:** identical to the NTD holdings already in the estate —
`data.transportation.gov` is reachable and labels its NTD datasets
`USGOV_WORKS`. This is the *strongest* rights class available and the estate
already has the pattern. **Lowest-friction item in this entire document.**

⚠️ **The NTD does not collect trip denials.** No table in the list is a denial
source. GAO said as much in **GAO-13-17, "ADA Paratransit Services: Demand Has
Increased, but Little is Known about Compliance"** (2012-11-15) — FTA "conducts
specialized ADA paratransit compliance reviews … however, **few transit agencies
are selected for review each year**", and FTA lacks documented selection
criteria, relying on "complaints, media reports, experience with an agency."
*(gao.gov is blocked; UNT's mirror renders a JS wall; this is from the UNT
catalogue record and search results — **the report body is unverified**.
Mirror: <https://digital.library.unt.edu/ark:/67531/metadc302667/>.)*

**That absence is the market.** The only national dataset of US transit operations
does not record the outcome Milexium exists to explain.

### 6.2 APTA

- Public Transportation Fact Book — <https://www.apta.com/news-research/about-the-industry/public-transportation-fact-book/>; PDFs are directly downloadable (e.g. `https://www.apta.com/wp-content/uploads/2017-APTA-Fact-Book.pdf`). `apta.com` is reachable.
- **Rights: UNVERIFIED, and presumed restrictive.** APTA is a trade association,
  not a government body; § 105 does not apply. `https://www.apta.com/terms-of-use/`
  returned **403** to this client — **I could not read the terms, so there is no
  rights verdict here.**
- **Low priority regardless**, on content: the Fact Book is largely a
  re-presentation of NTD, which the estate already holds at source under a
  clean licence. Taking a restrictively-licensed derivative of data we already
  hold cleanly is a bad trade.
- ⚠️ Fact Book PDFs also circulate on **Scribd**. Ignore those entirely —
  third-party republication with no rights basis.

### 6.3 State DOT and agency performance reporting

Weakest category examined; reported honestly rather than padded.

- **MBTA** publishes RIDE performance (OTP, complaints per 1,000 trips) via
  press releases and dashboards; MBTA/MassDOT rights are **already recorded as
  machine-unverifiable in ADR-0050 and the `ACQUISITION_PLAN`**. No change.
- **MTA Access-A-Ride Dashboard** publishes OTP. MTA terms are already a
  **no-new-acquisitions** call in the `ACQUISITION_PLAN` (revocability plus a
  possible commercial licence fee). **That verdict stands and this does not
  reopen it** — note only that the DOJ letter in §3 quotes AAR performance
  data, and *that* route is public domain. **Take the regulator's copy, not the
  operator's.** That is a general principle worth adopting: where a regulator
  has restated an operator's numbers, the regulator's document is both
  rights-cleaner and independently authoritative.
- I found **no state DOT publishing a structured, multi-operator paratransit
  performance series** comparable to Cal-ITP's GTFS work. Possible I missed one;
  I did not find one, and I am not going to imply otherwise.

---

## 7. Rights verdicts — summary

| Source | Commercial use? | Basis | Where it says so |
|---|---|---|---|
| **FTA ADA compliance reviews** | **Yes** | US federal work, 17 U.S.C. § 105 | <https://www.usa.gov/government-copyright> — **no per-document label**; contractor-authorship caveat |
| **DOJ findings letters / briefs / decrees** | **Yes** | US federal work (US Attorneys) | same; no contractor caveat |
| **Court opinions** | **Yes** | Government edicts doctrine; *Georgia v. Public.Resource.Org*, 590 U.S. 255 (2020) | no copyright subsists |
| **CourtListener bulk CSV** | **Yes** | **Public Domain Mark** | <https://wiki.free.law/c/courtlistener/help/api/bulk-data/bulk-legal-data> |
| CourtListener *site content* | ⚠️ **Unverified — possibly CC BY-ND** | search snippet only | <https://www.courtlistener.com/terms/> — **unreadable, bot challenge. Verify in a browser.** |
| **NTD unused tables** | **Yes** | `USGOV_WORKS` | `data.transportation.gov` dataset metadata (pattern already in estate) |
| **TCRP reports** | ❌ **NO** | **© National Academy of Sciences, all rights reserved**; permission limited to **"classroom and not-for-profit purposes"** | report front matter, quoted verbatim §5 |
| APTA Fact Book | ⚠️ **Unverified** | trade association, § 105 does not apply | <https://www.apta.com/terms-of-use/> — **403, could not read** |
| Justia | ⚠️ **Unverified** | — | blocks automated reading |
| MBTA / MassDOT | ⚠️ **Unverified** | unchanged from ADR-0050 | — |
| MTA / NYC | ❌ **No new acquisitions** | unchanged from `ACQUISITION_PLAN` | <https://www.mta.info/terms-and-conditions> |
| Scribd copies of anything | ❌ **No** | third-party republication, no rights basis | — |
| CourtListener 2 TB embeddings | ❌ **No** | **~$200 AWS fees — paid service** | <https://wiki.free.law/c/courtlistener/help/api/bulk-data/bulk-legal-data> |
| PACER | ❌ **No** | **paid, per-page** | hard constraint |

---

## 8. What I ruled out, and why

- **PACER** — paid per page. Out on the hard constraint. CourtListener/RECAP
  covers opinions fully and dockets partially; that is enough to proceed and
  there is no free substitute for the rest.
- **CourtListener's 2 TB embeddings corpus** — ~$200 of AWS egress. Paid
  service. Out. (The ordinary CSV bulk files are free and stay in.)
- **TCRP as a *data source*** — copyright is real and the permission grant
  explicitly excludes commercial use. Retained as a **citation source** only.
  This is the one place where "it's free to download" and "we may use it" come
  apart, and it would have been easy to get wrong.
- **APTA Fact Book** — rights unreadable, and content largely duplicates NTD
  which we already hold under a better licence. Ruled out on both counts.
- **Scribd-hosted copies** of APTA/TCRP material — no rights basis whatever.
- **ADA paratransit eligibility rosters / individual complaint records** —
  already correctly excluded by the `ACQUISITION_PLAN` as health data about
  named people. Nothing found here changes that; note that the FTA reviews
  *discuss* eligibility determinations in aggregate, which is the right
  granularity and is already public.
- **GAO-13-17 full text** — not ruled out, just **unread**: `gao.gov` blocked,
  UNT mirror JS-walled. Worth ten minutes of a human's time; likely contains a
  useful aggregate characterisation of the compliance-review programme.
- **State DOT paratransit performance series** — searched, not found. Recorded as
  a negative result rather than dressed up.

---

## 9. Literature that backs the method

For each: the canonical reference, whether free full text exists (**verified by
HTTP request unless marked otherwise**), and — the part that matters —
**where our implementation differs from the published result.**

### 9.1 Dial-a-ride / DARP — the benchmark claim

**Canonical:**
- **Cordeau, J.-F., & Laporte, G. (2003).** "A tabu search heuristic for the
  static multi-vehicle dial-a-ride problem." *Transportation Research Part B*
  **37**(6), 579–594. — *introduces the standard random instances*
- **Cordeau, J.-F. (2006).** "A branch-and-cut algorithm for the dial-a-ride
  problem." *Operations Research* **54**(3), 573–586. — ***this is where the
  published optima come from***
- **Ropke, S., Cordeau, J.-F., & Laporte, G. (2007).** "Models and branch-and-cut
  algorithms for pickup and delivery problems with time windows." *Networks*
  **49**(4), 258–272. — *pushed the exactly-solved frontier from 36 to 96 requests*
- Surveys: **Cordeau & Laporte (2007)**, *Annals of OR* **153**, 29–46;
  **Ho, Szeto, Kuo, Leung, Petering & Tou (2018)**, "A survey of dial-a-ride
  problems: Literature review and recent developments," *TR-B* **111**, 395–421.

**Free full text:** ❌ **No** for the two load-bearing papers. I verified that
`https://pubsonline.informs.org/doi/pdf/10.1287/opre.1060.0283` returns an
**HTML landing page, not a PDF** — Cordeau 2006 is paywalled. TR-B 2003 is
Elsevier, paywalled. Author copies circulate on ResearchGate; I did not verify
their provenance and **would not rely on them**.

✅ **The instances themselves are free and live — verified:**
`http://neumann.hec.ca/chairedistributique/data/darp/`
with `branch-and-cut/` (`a2-16`, `a2-20`, `a2-24`, `a3-18` … `a8-64`, plus the
`b`-series) and `tabu/`. Open directory listing, no key, no account.
⚠️ **No licence statement of any kind on that host.** Academic-norm free use with
citation is the near-universal practice, but this is **an unverified rights
position** and should be recorded as such — do not upgrade it to "public domain."

**Where we differ — state this, do not let it be discovered.**
Cordeau's instances are **Euclidean, single-depot, homogeneous-fleet**, with
uniform-random requests, no wheelchair/ambulatory distinction, no commingling,
no real road network, and an objective of routing cost subject to ride-time and
time-window constraints. **US ADA paratransit is none of those things.**

So "we reproduce the published optima" is a **solver-correctness claim** — our
implementation finds the known optimum on a standard instance set, which is
evidence the optimiser is right. It is **not** a claim that the benchmark
represents US paratransit, and it must never be presented as one. Note also
*which* optima: the small-instance optima are Cordeau (2006); anyone citing
"largest solved to optimality" should say 36 requests (Cordeau 2006) or 96
(Ropke et al. 2007), not conflate them.

### 9.2 Online / dynamic vehicle routing — the "same-day is harder" claim

**Canonical:**
- **Ascheuer, N., Krumke, S. O., & Rambau, J. (2000).** "Online dial-a-ride
  problems: Minimizing the completion time." *STACS 2000*, LNCS **1770**,
  639–650. — SMARTSTART is **2-competitive**, matching a lower bound of 2 on
  general metric spaces
- **Feuerstein, E., & Stougie, L. (2001).** "On-line single-server dial-a-ride
  problems." *Theoretical Computer Science* **268**(1), 91–105. — lower bounds on
  the line
- ⭐ **Jaillet, P., & Wagner, M. R. (2006).** "Online routing problems: Value of
  advanced information as improved competitive ratios." *Transportation Science*
  **40**(2), 200–210.
- Framework: **Borodin, A., & El-Yaniv, R. (1998).** *Online Computation and
  Competitive Analysis.* Cambridge UP.

**Free full text:**
- ✅ **Jaillet & Wagner (2006) — verified free**, author copy on MIT:
  `http://web.mit.edu/~jaillet/www/general/online_routing_ts_1_06.pdf`
  (302,115 bytes, `application/pdf`)
- ❌ Ascheuer et al. — Springer LNCS, paywalled. A ZIB technical-report version
  likely exists; `opus4.kobv.de` served a bot challenge, so **unverified**.
- ❌ Feuerstein & Stougie — Elsevier, paywalled.

**Jaillet & Wagner is the citation you actually want.** It quantifies **the value
of advance information as an improvement in competitive ratio** — which is
*precisely* the next-day-batching vs same-day claim, stated as a theorem rather
than an intuition. Ascheuer et al. establishes that online DARP has a hard
constant-factor gap; Jaillet & Wagner establishes that **knowing requests
earlier provably shrinks that gap.** Lead with the latter.

**Where we differ — and this one is easy to overclaim.**
Competitive ratios are **worst-case against an adversary**, on **completion-time
or latency objectives**, on abstract metric spaces. They say: *no online
algorithm can guarantee better than 2× the offline optimum.* They do **not** say
anything about expected performance on real demand, and they say **nothing about
denial rates** — denial is not the objective in any of these papers.

Defensible: *"Same-day commingled service is provably harder than next-day
batching in the online-algorithms sense: there is a proven constant-factor gap
to the offline optimum, and advance information provably narrows it
(Jaillet & Wagner 2006)."*
**Not** defensible: *"The literature shows same-day service produces N% more
denials."* It does not, and no amount of citation will make it.

### 9.3 Conformal prediction — the withdrawn-guarantee claim

**Canonical:**
- **Vovk, V., Gammerman, A., & Shafer, G. (2005).** *Algorithmic Learning in a
  Random World.* Springer. — the foundational text
- **Shafer, G., & Vovk, V. (2008).** "A tutorial on conformal prediction."
  *JMLR* **9**, 371–421.
- **Lei, J., G'Sell, M., Rinaldo, A., Tibshirani, R. J., & Wasserman, L. (2018).**
  "Distribution-free predictive inference for regression." *JASA* **113**(523),
  1094–1111.
- ⭐ **Barber, R. F., Candès, E. J., Ramdas, A., & Tibshirani, R. J. (2023).**
  "Conformal prediction beyond exchangeability." *Annals of Statistics*
  **51**(2), 816–845.
- **Tibshirani, R. J., Barber, R. F., Candès, E. J., & Ramdas, A. (2019).**
  "Conformal prediction under covariate shift." *NeurIPS.*
- **Angelopoulos, A. N., & Bates, S. (2023).** "A gentle introduction to conformal
  prediction and distribution-free uncertainty quantification."

**Free full text — the best-supplied topic in this list:**
- ✅ **Shafer & Vovk (2008) — verified free**, `https://www.jmlr.org/papers/volume9/shafer08a/shafer08a.pdf` (764,429 bytes, `application/pdf`)
- ✅ **Barber et al. (2023) — verified free**, arXiv:2202.13415 (title and all four authors confirmed from arXiv metadata). *Annals of Statistics* is open access; the Project Euclid direct-PDF link returned a redirect stub, so **cite arXiv**.
- ✅ **Angelopoulos & Bates — verified free**, arXiv:2107.07511
- ✅ **Lei et al. (2018) — free**, arXiv:1604.04173
- ❌ Vovk et al. (2005) — book, paywalled

**Where we differ — and this is the most important divergence in the section.**

Milexium's intervals **withdraw the guarantee** when exchangeability breaks.
Barber et al. (2023) do something **strictly stronger and different**: they
prove the coverage gap is bounded by a term involving the **total-variation
distance between the data distribution and its permutations**, so the guarantee
**degrades gracefully and quantifiably** rather than vanishing.

So:
- ✅ Honest: *"Distribution-free coverage holds only under exchangeability
  (Vovk et al. 2005; Shafer & Vovk 2008), and our runtime withdraws the
  guarantee when it detects that assumption is violated. This is a deliberately
  conservative engineering choice."*
- ❌ Overclaim: *"Our approach implements Barber et al. (2023)."* It does not.
  Withdrawing a guarantee is **not** the same as bounding how much of it you
  lost, and a reviewer who knows this literature will spot the difference
  immediately. If anything, framing ours as conservative *relative to* the
  published result is the stronger position — and it points at a real roadmap
  item: bound the gap instead of dropping the claim.
- ⚠️ Also worth stating plainly: **detecting non-exchangeability is itself a
  statistical problem with its own error rates.** The withdrawal trigger is not
  guaranteed correct, and the honest framing says so.

### 9.4 Newsvendor / asymmetric cost — the 0.734 critical ratio

**Canonical:**
- **Arrow, K. J., Harris, T., & Marschak, J. (1951).** "Optimal inventory
  policy." *Econometrica* **19**(3), 250–272. — the formalisation; critical
  ratio `Cu / (Cu + Co)`
- **Koenker, R., & Bassett, G. (1978).** "Regression quantiles." *Econometrica*
  **46**(1), 33–50. — pinball loss ↔ quantiles
- ⭐ **Gneiting, T. (2011).** "Making and evaluating point forecasts." *JASA*
  **106**(494), 746–762.

**Free full text:**
- ✅ **Gneiting (2011) — verified free**, arXiv:0912.0902 (title and author
  confirmed from arXiv metadata)
- ❌ Arrow, Harris & Marschak (1951) — JSTOR, paywalled
- ❌ Koenker & Bassett (1978) — JSTOR, paywalled

**Gneiting (2011) is the citation to lead with**, and it is the free one. It
establishes **elicitability**: the optimal point forecast is determined by the
loss function — squared error elicits the **mean**, piecewise-linear (pinball)
loss with asymmetry α elicits the **α-quantile**. That is *exactly* the
0.734-vs-0.5 argument, stated as a general result about forecast evaluation,
and it applies to Milexium's setting far more directly than an inventory model
does.

**Where we differ.**
- The newsvendor result is **single-period, single-product, known-cost**.
  Paratransit capacity is **multi-period with carry-over** — drivers and
  vehicles are committed on rosters and runs, not restocked each morning. The
  newsvendor is therefore a **motivating analogy**, and the load-bearing
  citation is elicitability (Gneiting), not inventory theory. Say it that way.
- **0.734 is an estimate, not a constant.** It is derived from measured cost
  asymmetry and inherits every assumption in that measurement. The claim
  "0.734 ≠ 0.5, therefore a squared-error objective targets the wrong
  functional" is **strong and well-supported**. The claim "the critical ratio is
  0.734" is a **measurement with an error bar** and should carry one, plus the
  cost inputs it came from.
- ⚠️ Watch the direction of the argument. Elicitability tells you *which
  functional* to target. It does **not** validate the underage/overage costs used
  to compute 0.734 — that is a separate empirical claim standing on its own
  evidence.

---

## 10. Verification log

**Verified by reading the primary source directly:**
- FTA ADA Compliance Review Final Reports index — full enumeration of all 119
  table rows (84 paratransit + 33 fixed-route + 2 header rows), agency names,
  locations, dates. Wayback capture `20260206170938`.
- **FTA/SEPTA September 2018 report** — read in full: table of contents, §6.4
  capacity-constraints subsections, the trip-denial finding, Table 6.5 OTP for
  12,755 trips, the "zero-denial policy" quotation, and the Summary Table schema.
- **FTA/MATA Memphis December 2020 report** — read in full: the 2.3% / 1.7%
  self-reported vs 27% / 37% observed denial rates, Table 6.4 missed trips by FY,
  the full list of Tables 4.1–6.7, and the agency response appendix.
- **DOJ Letter of Findings, NYCTA Access-A-Ride, 2022-10-17** — read in full
  (7 pp.); all percentages quoted in §3 are verbatim.
- **DOJ amicus brief, *Liberty Resources v. SEPTA*, 2000-12-15** — read live at
  `archive.ada.gov`; all denial statistics verbatim.
- ***Dilworth v. City of Detroit* consent decree** — read live; numeric
  obligations and reporting schedule.
- **CourtListener opinion search** — returned and confirmed the four cases in §4.
- **CourtListener bulk-data documentation** — Public Domain Mark; S3 bucket URL;
  the ~$200 embeddings fee.
- **TCRP Synthesis 174 front matter** — year, ISBN, DOI, sponsors, full panel
  roster, 37-provider survey, 5 case examples, copyright verbatim.
- **TRB TCRP synthesis index** — report numbers and dates for Syntheses 161, 163,
  165, 168, 174.
- **NAP catalog** — confirmed "Download as a Guest" requires an email address but
  no account.
- **`onlinepubs.trb.org/onlinepubs/tcrp/tcrp_rpt_88.pdf`** — 4,113,008 bytes,
  `application/pdf`, no account.
- **`usa.gov/government-copyright`** — federal-works statement and all four
  exceptions.
- **FTA NTD data-product list** — via Wayback 2025 capture.
- **Cordeau DARP instance directory** — live, open listing, instance filenames.
- **Free-text HTTP verification** for: Jaillet & Wagner (MIT, 302 KB PDF),
  Shafer & Vovk (JMLR, 764 KB PDF), and arXiv metadata for Barber et al.
  (2202.13415), Angelopoulos & Bates (2107.07511), Gneiting (0912.0902).

**Established from search results and secondary sources — NOT read in the
primary source:**
- The DOJ enforcement-action list in §3 (dates for Maryland MTA, Honolulu, NJ
  Transit, County of Hawaii, Muskegon, Virgin Islands, Jackson). NYCTA, SEPTA
  and Detroit were read directly; **the rest are unverified.**
- The *Liberty Resources* **remedy** — "no more than five trip denials daily"
  plus fines — from Disability Rights Pennsylvania, not from the order.
- The **Jackson/JTRAN** consent decree terms — 10 denials/month, >60-minute
  definition — from press reporting.
- The *Liberty Resources* court **reasoning** quotation in §4. **Verify before
  using in any external material.**
- **GAO-13-17** content — catalogue record and search results only.
- **CourtListener site licence (CC BY-ND)** — search snippet only; the terms page
  is bot-challenged. **Must be checked in a browser.**

**Could not verify at all:**
- **The survey tables inside TCRP Syntheses 135, 168 and Report 124** — the NAP
  reader serves page images, not text. Respondent counts and whether they carry
  before/after operational metrics are **unknown**. Largest content gap here.
- **APTA terms of use** — 403.
- ***Liberty Resources* opinion full text** — CourtListener and Justia both
  bot-challenge document pages.
- **Whether the NTD Facility Inventory carries facility coordinates** — the one
  fact that would make it a deadhead input rather than a count.
- **Any file size in this document except the four PDFs explicitly measured.**
- Whether FTA's compliance-review programme is paused, ended, or merely
  unpublished since March 2021.

---

## 11. Recommended next actions

Free, no registration, no payment. **If any step asks for a credit card, stop —
that means something here is wrong.**

1. **Open five pages in a browser and capture them for the rights record.**
   Ten minutes, and it converts the largest unverified items into settled ones:
   - `https://www.transit.dot.gov/regulations-and-guidance/civil-rights-ada/ada-compliance-review-final-reports` — confirm the list matches §2 and that nothing post-2021 exists
   - `https://www.courtlistener.com/terms/` — **the BY-ND question**
   - `https://www.apta.com/terms-of-use/`
   - `https://www.transit.dot.gov/regulations-and-guidance/civil-rights-ada/ada-compliance` — the DOJ action list in §3
   - any one TCRP synthesis PDF — confirm the copyright notice matches §5

2. **Take the NTD tables now.** Contractual Relationship, Monthly Modal Time
   Series, Facility Inventory, TS2.2, TS4.1. Same host, same licence, same
   pattern as holdings already in the estate. Hours of work, `USGOV_WORKS`
   rights, no open questions. **This is the only item with zero unresolved
   dependencies — do it first.**

3. **Harvest the 84 FTA paratransit reviews + the DOJ actions.** ~100 documents,
   ~1–3 GB total. Then build the structured extraction: `agency × review_date ×
   CFR_requirement × deficiency_status`, plus the metric tables. **This is the
   single highest-value item in this document** and it produces an asset that
   does not currently exist in public.
   Record rights as *"US federal work, 17 U.S.C. § 105, no explicit label"* with
   the contractor caveat noted — **not** as "public domain, declared."

4. **Align the denial taxonomy to 49 CFR § 37.131(f)** and cite FTA's own
   operationalisation (§2). Specifically: a negotiated offer beyond ±60 minutes
   is a denial **even if accepted**, and a denied leg denies the dependent
   return. Free, and it makes the denial record *regulator-legible* — which is
   worth more than any dataset here.

5. **Fix the four literature claims** per §9 before any of them goes external —
   especially the conformal one, where the published result is stronger than
   ours and the honest framing is the more credible one anyway. Lead with the
   three free, load-bearing citations: **Jaillet & Wagner (2006)**,
   **Gneiting (2011)**, **Barber et al. (2023)**.

6. **Read the TCRP surveys in a browser** (Syntheses 135, 168, and Report 124)
   and record respondent counts and whether they carry operational metrics.
   Synthesis 168 on continuous dynamic optimization is the competitive-landscape
   document. **Read; do not ingest.**

7. **Do not treat TCRP as acquirable.** © NAS, all rights reserved, permission
   limited to classroom and not-for-profit use. Cite the facts, never reproduce
   the expression. If a specific table is genuinely needed, **email NAS for
   permission** — routine, free, and a named counterparty, unlike every other
   open question in this document.
