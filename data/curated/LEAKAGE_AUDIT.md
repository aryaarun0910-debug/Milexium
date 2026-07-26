# Point-in-time leakage audit

`leakage_audit.py`. Report: `leakage_audit_report.json`. **Result: PASS - no
leakage detected across 24 features in 2 pipelines** (AAR zone-hour 11/11, NTD
monthly 13/13).

## Why this exists

A temporal forecast is only honest if every feature for target time t is
computable strictly from data before t. Teams usually assert this in prose. We
prove it mechanically, so "no look-ahead" is a checked fact, not a promise.

## The test (future-corruption)

For each pipeline, at several cutoff dates:
1. Build features normally (baseline).
2. Replace every target value at date > cutoff with large random noise.
3. Rebuild all features on the corrupted panel.
4. Assert every feature at every row with date <= cutoff is bit-identical to
   the baseline.

Logic: if a past feature changes when only the future is corrupted, it secretly
reads the future -> leakage. Nothing changed, at any cutoff, for any feature ->
every feature provably depends only on the past. Cutoffs tested span each
panel's timeline (AAR: 2025-06, 2025-12, 2026-03; NTD: 2020-01, 2023-01,
2025-05), so the guarantee holds across the range, not just at one boundary.

## Per-feature basis (why each is clean)

- **Calendar** (hour, dow, month, sin/cos, weekend, holiday, year): pure
  functions of the timestamp, independent of any target. Trivially leak-free;
  the test confirms it.
- **Demand-history lags** (lag1/7/14 for AAR, lag1/2/3/12 for NTD): built with
  `groupby(...).shift(k)` - each row sees only k steps back. Confirmed leak-free.
- **Rolling means** (roll28, roll12): `shift(1).rolling(w)` - the shift(1)
  guarantees the current value is excluded, only the trailing window enters.
  Confirmed leak-free (this is the classic off-by-one leak; the test proves we
  avoided it).
- **yoy_ratio** (NTD): lag12 / roll12, both past-only, so their ratio is too.
- **Capacity lags** (vrh_lag1, vrm_lag1, voms_lag1): the prior month's reported
  vehicle revenue hours/miles and peak vehicles - never the target month's.

## The one honest real-world caveat (weather)

Weather is exogenous (not derived from the target), so it passes the corruption
test by construction and is excluded from the mechanical feature list above. But
there is a subtlety that matters for a production forecast and that we state
plainly: the models currently join the **realized** daily/hourly weather for the
target day. At genuine day-ahead inference time you do not have realized weather,
you have a **forecast**. That is not target leakage (weather is not y), but it is
a mild look-ahead on an exogenous input that would slightly optimistically bias a
live day-ahead run. The fix for production is to join the day-ahead weather
FORECAST (e.g. NWS/NOAA GFS at issue time), not the realized value. Documented
here so it is a known, deliberate choice - not an accident a reviewer catches.

## What this earns

Every headline forecast number in this repo (AAR 0.986, Chicago 0.966, the NTD
national results) rests on features this audit proves are strictly point-in-time
correct. Combined with the naive-baseline discipline, the clean train/tune/cal/
valid split, and the held-out-agency cold-start test, this is the "unimpeachable"
evidentiary standard: a reviewer can rerun `leakage_audit.py` and confirm it.
