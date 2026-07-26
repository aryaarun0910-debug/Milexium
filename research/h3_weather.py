"""H3 -- does weather explain demand-response demand at monthly resolution?

Run:  py -3 research/h3_weather.py

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
"""

from __future__ import annotations

import json
import math
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib import MONTHLY, env, mean, ols, parse_month, pearson, say  # noqa: E402

CACHE = HERE / "noaa_gsom_cache.json"

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


def load_weather():
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    wx = {}
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:
        fetched = list(ex.map(_one, AGENCIES.items()))
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
    CACHE.write_text(json.dumps(wx), encoding="utf-8")
    return wx


def main() -> None:
    say("fetching monthly weather...")
    wx = load_weather()
    say(f"stations with data: {len(wx)}")

    # ---- monthly DR ridership -------------------------------------------
    upt = defaultdict(float)
    import csv

    with open(MONTHLY, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if row["Mode"] != "DR" or row["NTD ID"] not in AGENCIES:
                continue
            y, m = parse_month(row["Date"])
            if y not in YEARS:
                continue
            v = row["UPT"].strip().replace(",", "")
            if v:
                upt[(row["NTD ID"], y, m)] += float(v)

    say(f"agency-months of DR ridership: {len(upt)}")

    # ---- build within-agency, within-calendar-month anomalies -------------
    series = defaultdict(list)
    for (nid, y, m), v in upt.items():
        if v > 0:
            series[nid].append((y, m, v))

    rows = []
    for nid, obs in series.items():
        if nid not in wx or len(obs) < 48:
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

    (HERE / "h3_weather.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    say("\nwrote research/h3_weather.json")


if __name__ == "__main__":
    main()
