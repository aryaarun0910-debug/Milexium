# YC submission: execution backlog (deadline Friday 25 July 2026)

Hard deadline: application submitted Friday morning UK time. The form, a 1-minute founder video, optionally a product demo video and URL.

No day-by-day scheduling. We execute the backlog top to bottom, continuously, at maximum throughput. Anything Claude can build or fetch gets built or fetched immediately; the only items with real calendar constraints are the human ones listed at the bottom. Refer back to this file every session, mark things done, add tasks as they appear.

## What YC actually evaluates here

Two UK students, pre-revenue, pre-launch. The application wins or loses on: (1) clarity about the problem and who has it, (2) evidence you talk to customers, (3) proof you ship fast, (4) founder energy in the video. Write like the notes in YC_APPLICATION_NOTES.md: direct, decisions stated, tradeoffs owned (including no US visa yet and willingness to relocate).

## Done

- Repo cleaned up, TransitPulse-first framing
- v1 synthetic pipeline: generator, demand model, audit-trail scheduler, 5 demo asset PNGs
- NTD data pull: full US demand-response universe, 3,075 agencies, 2022-2024 (ntd/raw/)
- Per-agency economics table: trips, cost/trip, deadhead share, value of a 10 percent deadhead cut per agency (ntd/agency_economics.csv)
- Bottom-up market sizing from NTD 2024: 1,920 agencies, 139.7M trips/yr, $7.06B opex, median $37.97/trip, 17.3 percent deadhead (ntd/market_sizing.md)
- Real paratransit demand data: 26.3M NYC Access-A-Ride bookings, hourly by borough, Jan 2024 to May 2026 (realdata/panels/)
- Real-data demand model with honest baseline: R2 0.987 vs 0.923 seasonal-naive, MAE 19.7 vs 55.5, strict 90-day temporal holdout, split-conformal intervals (realdata/metrics_real.json)

## In progress

- Chicago TNP zone-hour panel, Nov 2018 to mid 2026, about 300M real door-to-door trips aggregated server-side (realdata/fetch_chicago_panel.py)
- Bulk NYC TLC FHVHV parquet download, about 1.5B trips, roughly 40 GB, for transformer-scale training (realdata/fetch_tlc_parquet.py, realdata/raw_tlc/)

## Next (engineering and data)

- Train Chicago zone-hour model when panel lands; report vs seasonal-naive
- DuckDB aggregation of TLC parquet to NYC zone-hour panel (realdata/aggregate_tlc.py)
- Kaggle GPU transformer: notebook that builds the TLC panel and trains a temporal transformer for multi-zone day-ahead forecasting; Arya runs it on Kaggle GPUs (kaggle/)
- Expand outreach targets to 50+ from ntd/agency_economics.csv, each row with a personalization hook (agency's own trips, cost/trip, deadhead dollars)
- Rebuild demo assets on real data (AAR forecasts with conformal bands beat synthetic screenshots)
- Retire the synthetic pipeline once real data covers everything it demonstrated (generator, R2 story, scheduler inputs). Do not delete before the audit-trail scheduler has a real-data replacement for its booking stream. Chicago TNP trip records can serve as scheduler input.
- /method page content with real citations: NTD tables, 49 CFR 37.131, model card, conformal coverage numbers
- Counterfactual backtest: proposed vs actual allocation on a replayed month
- Computed version of the capacity-alert suggested action

## Next (application and site)

- docs/yc-application-draft.md: full draft of every answer. Hardest first: what are you making, why this, why you, competitors (Ecolane, TripSpark, RouteMatch/Uber Health, incumbent opacity is the opening), progress, equity split
- Grill pass on the full application (/grill-me), cut every hedge
- Vision section: paratransit beachhead, then campus/hub/small fixed-route with the same engine
- Website first pass (Arya builds, Chris iterates): deliberately LAST, after the data and models sell themselves
- Demo video 60-90s: screen capture over real-data assets, Arya narrates problem, prediction, one scheduled trip, its explanation

## Human-only (real calendar constraints)

- Arya: register domain, set up branded email (outreach from a domain replies better than gmail)
- Arya: queue outreach waves for 8-9am US Eastern on weekdays; replies are human-latency, so send early and wide
- Both: equity split and CEO-on-the-form settled before submission; YC asks, do not leave it vague
- Arya: EWB competition IP terms check (YC asks about encumbrances); one email to EWB if ambiguous
- Both: founder video, one take style, 60 seconds, phone camera fine; rehearse until it does not sound rehearsed
- Any replies: book calls immediately, even post-25th; "calls booked with paratransit operators" is a legitimate traction line

## Rules

- Outreach and the application gate everything; engineering runs at maximum ambition in parallel, never instead
- Every number quoted publicly comes from a committed, reproducible script in this repo
- Real-data numbers and synthetic numbers are never mixed in one claim; EWB's 0.94 R2 is never reused for TransitPulse
- Every EWB mention is one credential line, never the identity
- Anything that slips, slips toward the /method page and wave 3 outreach, never toward the application, the videos, or wave 1
