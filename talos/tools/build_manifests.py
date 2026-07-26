"""Immutable provenance manifests for every committed data panel.

For each modeled panel we record, in a versioned JSON manifest: the exact
public source (dataset id + portal + fetch script), when it was built, a
sha256 content checksum, the schema (columns + dtypes), and the coverage
(row count, date range, distinct entities). This is the data-provenance /
lineage backbone: anyone can verify our panels are what we say, trace each
back to its public origin, and detect silent drift (a changed checksum means
the data changed).

This is deliberately part of the "our edge is how we build raw data from
scratch" thesis: a panel with a manifest is auditable; a CSV with no
provenance is a liability.

Output: data/curated/manifests/<panel>.json + data/curated/manifests/index.json
Run:    py -3 talos/tools/build_manifests.py
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PANELS = ROOT / "data" / "curated" / "panels"
OUT = ROOT / "data" / "curated" / "manifests"
OUT.mkdir(parents=True, exist_ok=True)

# panel filename -> provenance (public source of record)
SOURCES = {
    "aar_hourly_borough.csv.gz": {
        "name": "NYC Access-A-Ride paratransit, hourly x borough",
        "portal": "data.ny.gov", "dataset_ids": ["hasd-hdb7"],
        "fetch_script": "data/curated/fetch_nyc_aar.py",
        "license": "NY Open Data (public domain)"},
    "aar_daily.csv": {
        "name": "NYC Access-A-Ride daily scheduled trips",
        "portal": "data.ny.gov", "dataset_ids": ["vxuj-8kew"],
        "fetch_script": "data/curated/fetch_nyc_aar.py",
        "license": "NY Open Data"},
    "chicago_tnp_zone_hour.csv.gz": {
        "name": "Chicago TNP rideshare, community-area x hour",
        "portal": "data.cityofchicago.org",
        "dataset_ids": ["m6dm-c72p", "n26f-ihde", "6dvr-xwnh"],
        "fetch_script": "data/curated/fetch_chicago_panel.py",
        "license": "City of Chicago Open Data"},
    "mta_bus_route_hour.csv.gz": {
        "name": "MTA bus AFC ridership, route x hour",
        "portal": "data.ny.gov", "dataset_ids": ["kv7t-n8in", "gxb3-akrn"],
        "fetch_script": "data/curated/fetch_mta_apc.py",
        "license": "NY Open Data"},
    "mta_subway_station_hour.csv.gz": {
        "name": "MTA subway AFC ridership, station x hour",
        "portal": "data.ny.gov", "dataset_ids": ["wujg-7c2s", "5wq4-mkjj"],
        "fetch_script": "data/curated/fetch_mta_apc.py",
        "license": "NY Open Data"},
    "ntd_monthly_dr.csv.gz": {
        "name": "NTD monthly demand-response ridership, nationwide",
        "portal": "data.transportation.gov", "dataset_ids": ["8bui-9xvu"],
        "fetch_script": "data/curated/fetch_ntd_monthly.py",
        "license": "FTA / US DOT (public domain)"},
    "weather_daily.csv": {
        "name": "Daily weather (NYC + Chicago)",
        "portal": "archive-api.open-meteo.com", "dataset_ids": ["ERA5 archive"],
        "fetch_script": "data/curated/fetch_weather.py",
        "license": "Open-Meteo (free, attribution)"},
    "weather_hourly.csv.gz": {
        "name": "Hourly weather (NYC LaGuardia + Chicago O'Hare)",
        "portal": "ncei.noaa.gov", "dataset_ids": ["LCD 72503014732", "LCD 72530094846"],
        "fetch_script": "data/curated/fetch_weather_hourly.py",
        "license": "NOAA NCEI (public domain)"},
}


def sha256(path: Path, buf=1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(buf):
            h.update(chunk)
    return h.hexdigest()


def coverage(df: pd.DataFrame) -> dict:
    cov = {"rows": int(len(df))}
    date_col = next((c for c in ("date", "day") if c in df.columns), None)
    if date_col:
        d = pd.to_datetime(df[date_col], errors="coerce")
        cov["date_min"] = str(d.min().date())
        cov["date_max"] = str(d.max().date())
    for ent in ("ntd_id", "borough", "area", "route", "station_id", "city"):
        if ent in df.columns:
            cov[f"distinct_{ent}"] = int(df[ent].nunique())
    return cov


if __name__ == "__main__":
    index = []
    for fname, src in SOURCES.items():
        path = PANELS / fname
        if not path.exists():
            print(f"skip (missing): {fname}")
            continue
        df = pd.read_csv(path, low_memory=False)
        manifest = {
            "panel": fname,
            "built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
            "source": src,
            "schema": {c: str(t) for c, t in df.dtypes.items()},
            "coverage": coverage(df),
        }
        (OUT / f"{fname}.json").write_text(json.dumps(manifest, indent=2))
        index.append({"panel": fname, "sha256": manifest["sha256"],
                      "rows": manifest["coverage"]["rows"],
                      "source": f"{src['portal']} {src['dataset_ids']}"})
        c = manifest["coverage"]
        print(f"{fname}: {c['rows']:,} rows, "
              f"{c.get('date_min','?')}..{c.get('date_max','?')}, "
              f"sha256={manifest['sha256'][:12]}...")

    (OUT / "index.json").write_text(json.dumps(
        {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "panels": index}, indent=2))
    print(f"\nwrote {len(index)} manifests to {OUT}/")
