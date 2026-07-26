"""H3 -- does weather explain demand-response demand at monthly resolution?

Run:      py -3 research/h3_weather.py            # reproduce from the pinned set
Verify:   py -3 research/h3_weather.py --verify   # fail if the artifact drifted
Refresh:  py -3 research/h3_weather.py --refresh  # re-fetch and REPLACE the pin

Prior, stated before looking: weather SHOULD matter (bad weather suppresses
discretionary trips and raises no-shows) but monthly aggregation may destroy the
signal. `realdata/WEATHER_ABLATION_RESULTS.md` already found weather adds
essentially nothing at DAILY resolution for one agency (NYC AAR, R2 0.9851 ->
0.9853). This is the different test: many agencies, monthly, nationally.

Design
------
25 large demand-response operators in distinct metros, each paired with its
metro's primary airport GHCND station. Monthly DR unlinked passenger trips come
from the NTD monthly file (Mode='DR', summed over type of service).

The test is WITHIN AGENCY and WITHIN CALENDAR MONTH: the outcome is the log
deviation of an agency's trips in month m from that agency's own average for
calendar month m, and the regressors are the same-shaped anomalies of
temperature, precipitation and snowfall at its station. That construction
removes agency size, secular trend and seasonality, so anything left is weather
covarying with demand.

COVID years 2020-2021 are excluded throughout: a service collapse would
masquerade as an enormous weather-independent shock.

Reproducibility (MX-CONF-GOVERNANCE-HOLE-012)
---------------------------------------------
This script used to fetch NOAA live and fall back to a gitignored cache, so what
it analysed depended on when you ran it and what was on your disk. It was not
reproducible, and an audit measured the drift: the committed artifact rests on
1,994 complete observations across 20 agencies, and a 2026-07-26 re-fetch of the
same stations, years and data types returned 1,886 across 19. The finding did
not move -- weather is null at monthly resolution either way -- but the SAMPLE
moved, so the committed JSON could not be regenerated from the committed code.

So the observation set is now PINNED in `h3_weather_observations.json`, which is
committed, content-hashed, and the only weather input a normal run reads. There
is no network call on the default path and no cache fallback. Re-fetching is
`--refresh`: a separate, explicit action that rewrites the pin, prints exactly
which stations and months changed, and deliberately does NOT touch the result
artifact -- regenerating that is a second, visible step.

WHY THE SAMPLE ACTUALLY MOVED. The obvious story is that NOAA revised its
history, and it is the wrong one. A full controlled re-fetch of the identical
request on 2026-07-26T09:01:15Z returned an observation set BYTE-IDENTICAL to the
pinned one -- 25 stations, 3,300 station-months, same sha256. The arithmetic
names the real cause: every agency in this panel contributes exactly 108 complete
agency-months, 1,994 - 1,886 = 108, and 20 - 19 = 1. The audit's rerun lost one
station whole. The old code dropped any station whose fetch raised, kept whatever
else came back, and wrote THAT to the cache -- so a single transient HTTP failure
silently redefined the sample and then froze it as the input of record.

GSOM remains a revisable series in principle, so a refresh may legitimately move
the sample; that possibility is recorded in the pin and in the artifact's
provenance instead of being asserted as the explanation for this incident. The
failure that did occur is now structurally blocked: `--refresh` refuses to write
a pin missing any declared station unless `--allow-partial` says so in the open,
and records the loss in the pin when it does.

The second input, the NTD monthly ridership table, is already immutable: it is
content-addressed in the governed estate and its sha256 is verified on every run.
Its bytes are gitignored (70 MB), so a checkout without them cannot run this
script at all -- it says so and stops, rather than quietly analysing less.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib import MONTHLY, env, mean, ols, parse_month, pearson, say  # noqa: E402

PINNED = HERE / "h3_weather_observations.json"
ARTIFACT = HERE / "h3_weather.json"

# The governed, content-addressed NTD monthly ridership table. Verified every
# run: if this table is ever re-acquired, the numbers below stop being the
# numbers this file describes, and that must be loud rather than silent.
MONTHLY_SHA256 = "529952083544f257a8dd27d034f5481309f3d604c4dd3999d635ea71a148bb66"
MONTHLY_CATALOG_RECORD = "data/catalog/ntd-monthly-ridership-all-modes.acquired.json"

SOURCE = "NOAA NCEI global-summary-of-the-month (GSOM), TAVG/PRCP/SNOW, standard units"

# Measured, not assumed. Written into the pin and the artifact so the next reader
# inherits the measurement rather than the plausible story.
SOURCE_STABILITY = {
    "revisable_in_principle": True,
    "revisability_note": (
        "GSOM publishes late reports and QC revisions, so a --refresh is allowed to "
        "return a different sample. That is why the analysed set is pinned rather "
        "than re-derived."
    ),
    "observed_discrepancy": (
        "The 2026-07-26 audit rerun produced 1,886 complete agency-months across 19 "
        "agencies against the published 1,994 across 20."
    ),
    "controlled_refetch": (
        "2026-07-26T09:01:15Z: a full re-fetch of the identical request (25 stations, "
        "2015-2025, TAVG/PRCP/SNOW, standard units) returned an observation set "
        "byte-identical to the pinned one -- 25 stations, 3,300 station-months, "
        "sha256 e735059a15789871...."
    ),
    "attribution": (
        "NOT an upstream revision. Every agency contributes exactly 108 complete "
        "agency-months; 1,994 - 1,886 = 108 and 20 - 19 = 1, so the rerun lost one "
        "station whole. The pre-pin code dropped any station whose fetch raised, kept "
        "the rest, and cached the incomplete set -- one transient HTTP failure "
        "silently redefined the sample and froze it."
    ),
    "guard": (
        "--refresh refuses to write a pin missing any declared station; "
        "--allow-partial overrides it and records the loss in the pin."
    ),
}

# NTD ID -> (label, GHCND station at the metro's primary airport)
AGENCIES = {
    "90154": ("LA Access Services", "GHCND:USW00023174"),  # LAX
    "50066": ("Pace (Chicago)", "GHCND:USW00094846"),  # O'Hare
    "20008": ("MTA New York City Transit", "GHCND:USW00094728"),  # Central Park
    "30034": ("Maryland Transit Administration", "GHCND:USW00093721"),  # BWI
    "50008": ("Metropolitan Council (Twin Cities)", "GHCND:USW00014922"),  # MSP
    "60008": ("Houston METRO", "GHCND:USW00012960"),  # IAH
    "90019": ("RTC of Southern Nevada", "GHCND:USW00023169"),  # Las Vegas
    "40034": ("Miami-Dade", "GHCND:USW00012839"),  # Miami
    "30030": ("WMATA", "GHCND:USW00013743"),  # DCA
    "60048": ("VIA Metropolitan Transit", "GHCND:USW00012921"),  # San Antonio
    "90003": ("City & County of Honolulu", "GHCND:USW00022521"),  # Honolulu
    "10003": ("MBTA", "GHCND:USW00014739"),  # Boston
    "80006": ("Denver RTD", "GHCND:USW00003017"),  # Denver
    "90030": ("Valley Metro (Phoenix)", "GHCND:USW00023183"),  # Sky Harbor
    "00001": ("King County Metro", "GHCND:USW00024233"),  # SeaTac
    "00008": ("TriMet (Portland)", "GHCND:USW00024229"),  # PDX
    "30019": ("SEPTA", "GHCND:USW00013739"),  # Philadelphia
    "40022": ("MARTA", "GHCND:USW00013874"),  # Atlanta
    "60056": ("DART (Dallas)", "GHCND:USW00003927"),  # DFW
    "50055": ("Detroit DOT", "GHCND:USW00094847"),  # Detroit
    "30040": ("Port Authority of Allegheny County", "GHCND:USW00094823"),  # Pittsburgh
    "70003": ("Bi-State (St. Louis)", "GHCND:USW00013994"),  # St. Louis
    "80005": ("Utah Transit Authority", "GHCND:USW00024127"),  # SLC
    "50021": ("Milwaukee County", "GHCND:USW00014839"),  # Milwaukee
    "50015": ("Greater Cleveland RTA", "GHCND:USW00014820"),  # Cleveland
}

YEARS = list(range(2015, 2020)) + list(range(2022, 2026))


# --------------------------------------------------------------------------
# the pinned observation set
# --------------------------------------------------------------------------
def observations_digest(observations: dict) -> str:
    """Content hash of the observations, independent of file layout.

    Canonical form: sorted keys, no whitespace. Reformatting the pin file cannot
    change this; changing a single reading must.
    """
    canonical = json.dumps(observations, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_pin(observations: dict, pin: dict) -> None:
    """Write the pin with one agency per line -- a refresh diff names the
    stations that moved instead of rewriting 3,300 lines."""
    pin = dict(pin, observations_sha256=observations_digest(observations))
    lines = ['{', '  "pin": ' + json.dumps(pin, indent=2).replace("\n", "\n  ") + ",", '  "observations": {']
    keys = sorted(observations)
    for i, nid in enumerate(keys):
        body = json.dumps(observations[nid], sort_keys=True, separators=(",", ":"))
        lines.append(f'    {json.dumps(nid)}: {body}' + ("," if i < len(keys) - 1 else ""))
    lines += ["  }", "}"]
    PINNED.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_pinned() -> tuple[dict, dict]:
    """Read the pinned observations and prove they are the ones that were pinned."""
    if not PINNED.exists():
        die(
            f"pinned observation set missing: {PINNED.name}. This script does not "
            "fetch on the default path -- restore the file from git, or run with "
            "--refresh to build a NEW pin, which is a deliberate change of evidence "
            "and may not reproduce the committed artifact."
        )
    payload = json.loads(PINNED.read_text(encoding="utf-8"))
    pin, observations = payload["pin"], payload["observations"]
    actual = observations_digest(observations)
    if actual != pin["observations_sha256"]:
        die(
            f"{PINNED.name} has been edited: observations hash {actual[:16]}... does "
            f"not match the recorded {pin['observations_sha256'][:16]}.... The pin is "
            "the record of what was analysed; regenerate it with --refresh rather "
            "than editing it by hand."
        )
    return pin, observations


def die(msg: str) -> None:
    say(f"\nFATAL: {msg}")
    raise SystemExit(2)


# --------------------------------------------------------------------------
# fetching -- reached ONLY by --refresh
# --------------------------------------------------------------------------
def fetch_ncei(station: str, y0: int, y1: int):
    """NCEI access API -- global-summary-of-the-month. No account required."""
    sid = station.split(":", 1)[1]
    url = (
        "https://www.ncei.noaa.gov/access/services/data/v1"
        f"?dataset=global-summary-of-the-month&stations={sid}"
        f"&startDate={y0}-01-01&endDate={y1}-12-31"
        "&dataTypes=TAVG,PRCP,SNOW&format=json&units=standard"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "milexium-research/1.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode())


def fetch_cdo(station: str, y0: int, y1: int):
    """NOAA CDO v2, using NOAA_CDO_TOKEN. Slower; used as a fallback."""
    tok = env("NOAA_CDO_TOKEN")
    if not tok:
        return []
    outrows = []
    for y in range(y0, y1 + 1):
        url = (
            "https://www.ncei.noaa.gov/cdo-web/api/v2/data?datasetid=GSOM"
            f"&stationid={station}&startdate={y}-01-01&enddate={y}-12-31"
            "&datatypeid=TAVG&datatypeid=PRCP&datatypeid=SNOW"
            "&units=standard&limit=1000"
        )
        req = urllib.request.Request(url, headers={"token": tok})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.loads(r.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            continue
        for rec in d.get("results", []):
            outrows.append(
                {"DATE": rec["date"][:7], rec["datatype"]: rec["value"]}
            )
    return outrows


def _one(item):
    nid, (label, station) = item
    for fn, name in ((fetch_ncei, "ncei"), (fetch_cdo, "cdo")):
        try:
            got = fn(station, YEARS[0], YEARS[-1])
            if got:
                say(f"  {label:<36} {name:<5} rows={len(got)}")
                return nid, label, station, got
        except Exception as e:  # noqa: BLE001
            say(f"  {label:<36} {name:<5} FAILED {type(e).__name__}")
    return nid, label, station, None


def shape(fetched) -> dict:
    """Rows as returned by NOAA -> {ntd_id: {station, label, months}}."""
    wx = {}
    for nid, label, station, got in fetched:
        if not got:
            continue
        bym = defaultdict(dict)
        for rec in got:
            d = rec.get("DATE", "")[:7]
            if not d:
                continue
            for k in ("TAVG", "PRCP", "SNOW"):
                if rec.get(k) not in (None, ""):
                    try:
                        bym[d][k] = float(rec[k])
                    except ValueError:
                        pass
        wx[nid] = {"station": station, "label": label, "months": dict(bym)}
    return wx


def refresh(allow_partial: bool = False) -> None:
    """Re-fetch NOAA and REPLACE the pin, reporting exactly what moved.

    Deliberately does not regenerate h3_weather.json: a refresh changes the
    evidence, and rewriting the conclusion in the same breath is how a changed
    sample gets to look like a stable result.
    """
    old_pin, old_obs = ({}, {})
    if PINNED.exists():
        old_pin, old_obs = load_pinned()

    say("re-fetching monthly weather from NOAA (this is the only path that hits the network)...")
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as ex:
        fetched = list(ex.map(_one, AGENCIES.items()))
    new_obs = shape(fetched)
    if not new_obs:
        die("re-fetch returned nothing for every station; pin left untouched")

    # The failure that actually corrupted this analysis once: a station's fetch
    # raises, it is quietly dropped, and the smaller sample becomes the input of
    # record. It does not get to be quiet twice.
    missing = [nid for nid in AGENCIES if nid not in new_obs]
    if missing and not allow_partial:
        die(
            f"{len(missing)} of {len(AGENCIES)} declared stations returned nothing: "
            + ", ".join(f"{AGENCIES[n][0]} ({AGENCIES[n][1]})" for n in missing)
            + ". This is exactly how the sample silently shrank from 1,994 "
            "observations to 1,886 before it was pinned. The pin was NOT written. "
            "Re-run when the source is healthy, or pass --allow-partial to pin the "
            "short set deliberately and record the loss in it."
        )

    old_digest = old_pin.get("observations_sha256", "(none)")
    new_digest = observations_digest(new_obs)
    say("\n=== REFRESH DELTA ===")
    say(f"  stations:       {len(old_obs)} -> {len(new_obs)} (declared: {len(AGENCIES)})")
    for nid in sorted(set(old_obs) | set(new_obs)):
        was = set(old_obs.get(nid, {}).get("months", {}))
        now = set(new_obs.get(nid, {}).get("months", {}))
        if was == now:
            continue
        label = AGENCIES.get(nid, (nid, ""))[0]
        say(
            f"  {label[:34]:<36} months {len(was):>3} -> {len(now):>3}"
            f"   +{len(now - was)} / -{len(was - now)}"
        )
    say(f"  observations sha256: {old_digest[:16]}... -> {new_digest[:16]}...")

    write_pin(
        new_obs,
        {
            "source": SOURCE,
            "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stations_requested": len(AGENCIES),
            "stations_missing": [AGENCIES[n][1] for n in missing],
            "years": [YEARS[0], YEARS[-1]],
            "years_excluded": [2020, 2021],
            "source_stability": SOURCE_STABILITY,
            "supersedes_observations_sha256": old_digest,
            "provenance": "fetched by research/h3_weather.py --refresh",
        },
    )
    if new_digest == old_digest:
        say(f"\nwrote {PINNED.name} -- the pinned sample is UNCHANGED (identical hash);")
        say("only the retrieval timestamp moved. The artifact still reproduces.")
        return
    say(f"\nwrote {PINNED.name} -- the pinned sample has CHANGED.")
    say("Nothing else was written. To regenerate the result on the new sample:")
    say("  py -3 research/h3_weather.py")
    say("Commit the pin and the artifact together, or the artifact stops being reproducible.")


# --------------------------------------------------------------------------
# the analysis
# --------------------------------------------------------------------------
def load_monthly_dr() -> tuple[dict, dict]:
    """Monthly DR ridership for the studied agencies, from the governed table."""
    if not MONTHLY.exists():
        die(
            f"NTD monthly ridership table missing: {MONTHLY}. It is 70 MB and lives "
            "in the gitignored raw zone, so a fresh checkout does not have it. "
            f"Re-acquire it through the governed estate ({MONTHLY_CATALOG_RECORD}) "
            "before running this analysis -- there is no partial-data fallback."
        )
    digest = hashlib.sha256(MONTHLY.read_bytes()).hexdigest()
    if digest != MONTHLY_SHA256:
        die(
            f"NTD monthly table is not the pinned one: {digest[:16]}... != "
            f"{MONTHLY_SHA256[:16]}.... The committed result describes the pinned "
            "table; re-pin deliberately rather than reporting numbers from a "
            "different input."
        )

    import csv

    upt: dict = defaultdict(float)
    rows_read = rows_matched = 0
    with open(MONTHLY, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            rows_read += 1
            if row["Mode"] != "DR" or row["NTD ID"] not in AGENCIES:
                continue
            y, m = parse_month(row["Date"])
            if y not in YEARS:
                continue
            v = row["UPT"].strip().replace(",", "")
            if v:
                rows_matched += 1
                upt[(row["NTD ID"], y, m)] += float(v)
    return upt, {
        "sha256": digest,
        "rows_read": rows_read,
        "rows_matched_dr_studied_agencies_in_years": rows_matched,
    }


def compute(pin: dict, wx: dict) -> dict:
    say(f"stations in pinned set: {len(wx)}")

    upt, monthly_meta = load_monthly_dr()
    say(f"agency-months of DR ridership: {len(upt)}")

    series = defaultdict(list)
    for (nid, y, m), v in upt.items():
        if v > 0:
            series[nid].append((y, m, v))

    dropped_no_weather = dropped_short = dropped_no_tavg = 0
    rows = []
    for nid, obs in series.items():
        if nid not in wx:
            dropped_no_weather += 1
            continue
        if len(obs) < 48:
            dropped_short += 1
            continue
        w = wx[nid]["months"]
        # agency's own log-mean for each calendar month
        bym = defaultdict(list)
        for y, m, v in obs:
            bym[m].append(math.log(v))
        base = {m: mean(vs) for m, vs in bym.items()}
        # station's own mean for each calendar month, per datatype
        wbym = defaultdict(lambda: defaultdict(list))
        for ym, d in w.items():
            yy, mm = int(ym[:4]), int(ym[5:7])
            if yy not in YEARS:
                continue
            for k, val in d.items():
                wbym[k][mm].append(val)
        wbase = {k: {m: mean(v) for m, v in mm.items()} for k, mm in wbym.items()}
        for y, m, v in obs:
            ym = f"{y}-{m:02d}"
            d = w.get(ym)
            if not d or "TAVG" not in d:
                dropped_no_tavg += 1
                continue
            rec = {
                "nid": nid,
                "year": y,
                "month": m,
                "dlog_upt": math.log(v) - base[m],
                "tavg_anom": d["TAVG"] - wbase["TAVG"][m],
            }
            for k in ("PRCP", "SNOW"):
                if k in d and m in wbase.get(k, {}):
                    rec[k.lower() + "_anom"] = d[k] - wbase[k][m]
            rows.append(rec)

    say(f"usable agency-months with weather: {len(rows)}  agencies: {len({r['nid'] for r in rows})}")

    full = [r for r in rows if "prcp_anom" in r and "snow_anom" in r]
    say(f"complete cases (TAVG+PRCP+SNOW): {len(full)}")

    def report(feats, label):
        X = [[r[f] for f in feats] for r in full]
        y = [r["dlog_upt"] for r in full]
        beta, r2 = ols(X, y)
        say(f"  {label:<44} R2 = {r2:.5f}")
        for f, b in zip(feats, beta[1:]):
            say(f"      {f:<16} coef {b:+.6f}")
        return {"features": feats, "r2": r2, "coefs": dict(zip(feats, beta[1:]))}

    say("\nPooled within-agency, within-calendar-month regression:")
    res = {
        "n_obs": len(full),
        "n_agencies": len({r["nid"] for r in full}),
        "models": {
            "tavg_only": report(["tavg_anom"], "log-trip anomaly ~ temp anomaly"),
            "all_weather": report(
                ["tavg_anom", "prcp_anom", "snow_anom"],
                "log-trip anomaly ~ temp + precip + snow",
            ),
        },
    }

    say("\nUnivariate correlations (pooled):")
    for f in ("tavg_anom", "prcp_anom", "snow_anom"):
        xs = [r[f] for r in full]
        ys = [r["dlog_upt"] for r in full]
        say(f"  corr(dlog trips, {f:<12}) = {pearson(xs, ys):+.4f}")
        res.setdefault("pooled_corr", {})[f] = pearson(xs, ys)

    say("\nPer-agency temperature-anomaly correlation (is the sign even stable?):")
    peragency = {}
    for nid in sorted({r["nid"] for r in full}):
        sub = [r for r in full if r["nid"] == nid]
        if len(sub) < 36:
            continue
        c = pearson([r["tavg_anom"] for r in sub], [r["dlog_upt"] for r in sub])
        cs = pearson([r["snow_anom"] for r in sub], [r["dlog_upt"] for r in sub])
        peragency[nid] = {"n": len(sub), "r_tavg": c, "r_snow": cs}
        say(f"  {AGENCIES[nid][0][:34]:<36} n={len(sub):>3}  r_tavg={c:+.3f}  r_snow={cs:+.3f}")
    res["per_agency"] = peragency
    pos = sum(1 for v in peragency.values() if v["r_tavg"] and v["r_tavg"] > 0)
    say(f"\n  agencies with POSITIVE temp correlation: {pos}/{len(peragency)}")
    negsnow = sum(1 for v in peragency.values() if v["r_snow"] and v["r_snow"] < 0)
    say(f"  agencies with NEGATIVE snow correlation:  {negsnow}/{len(peragency)}")
    res["n_positive_tavg"] = pos
    res["n_negative_snow"] = negsnow

    # Everything below is a property of the inputs, not of the run: no wall clock,
    # no machine identity, nothing that would make a rerun differ from this file.
    res["provenance"] = {
        "reproduce": "py -3 research/h3_weather.py",
        "drift_check": "py -3 research/h3_weather.py --verify",
        "refresh": "py -3 research/h3_weather.py --refresh  (replaces the pinned sample)",
        "weather_observations": {
            "pin_file": "research/h3_weather_observations.json",
            "observations_sha256": pin["observations_sha256"],
            "retrieved_at": pin.get("retrieved_at"),
            "revalidated_at": pin.get("revalidated_at"),
            "source": pin.get("source", SOURCE),
            "source_stability": pin.get("source_stability", SOURCE_STABILITY),
            "stations_pinned": len(wx),
            "station_months_pinned": sum(len(v["months"]) for v in wx.values()),
        },
        "ridership_input": {
            "path": "data/raw/public/" + MONTHLY.name,
            "catalog_record": MONTHLY_CATALOG_RECORD,
            **monthly_meta,
        },
        "sample_construction": {
            "agencies_declared": len(AGENCIES),
            "agencies_with_dr_ridership": len(series),
            "agencies_dropped_no_pinned_weather": dropped_no_weather,
            "agencies_dropped_under_48_months": dropped_short,
            "agency_months_dr_before_join": len(upt),
            "agency_months_dropped_no_tavg": dropped_no_tavg,
            "agency_months_joined": len(rows),
            "agency_months_dropped_incomplete_weather": len(rows) - len(full),
            "agency_months_analysed": len(full),
            "agencies_in_per_agency_table": len(peragency),
            "per_agency_min_months": 36,
            "years_excluded": [2020, 2021],
        },
        "environment": {
            "python": ">=3.10",
            "third_party_dependencies": "none -- standard library only",
        },
    }
    return res


def main(argv: list[str]) -> None:
    if "--refresh" in argv:
        refresh(allow_partial="--allow-partial" in argv)
        return

    say("loading pinned monthly weather (no network on this path)...")
    pin, wx = load_pinned()
    res = compute(pin, wx)
    text = json.dumps(res, indent=2)

    if "--verify" in argv:
        if not ARTIFACT.exists():
            die(f"{ARTIFACT.name} does not exist, so there is nothing to verify against")
        committed = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        if committed == res:
            say(f"\nVERIFIED: {ARTIFACT.name} reproduces exactly from the pinned sample.")
            return
        say(f"\nDRIFT: {ARTIFACT.name} does NOT reproduce from the pinned sample.")
        for k in ("n_obs", "n_agencies"):
            say(f"  {k}: committed {committed.get(k)}  recomputed {res.get(k)}")
        changed = sorted(
            k for k in set(committed) | set(res) if committed.get(k) != res.get(k)
        )
        say(f"  differing top-level keys: {changed}")
        raise SystemExit(1)

    ARTIFACT.write_text(text, encoding="utf-8")
    say(f"\nwrote research/{ARTIFACT.name}")


if __name__ == "__main__":
    main(sys.argv[1:])
