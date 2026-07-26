"""Bulk-download NYC TLC High Volume For-Hire Vehicle trip parquet files.

FHVHV = every Uber/Lyft/Via trip in NYC, roughly 20 million rows a month,
February 2019 onward, published as monthly parquet (400-500 MB each) on the
TLC CloudFront CDN. This is the transformer-scale corpus: about 1.5 billion
real door-to-door trips with pickup zone and timestamp.

Files land in data/curated/raw_tlc/ (gitignored). Skips files already present,
so it can be re-run to resume. Stops cleanly at the newest published month.

Usage:
  py -3 data/curated/fetch_tlc_parquet.py            # 2019-02 through newest
  py -3 data/curated/fetch_tlc_parquet.py 2024-01    # start from a given month
"""

import sys
import time
from datetime import date
from pathlib import Path

import requests

RAW = Path(__file__).parent / "raw_tlc"
RAW.mkdir(parents=True, exist_ok=True)

CDN = "https://d37ci6vzurychx.cloudfront.net/trip-data"
START = sys.argv[1] if len(sys.argv) > 1 else "2019-02"


def months_from(start: str):
    y, m = map(int, start.split("-"))
    today = date.today()
    while (y, m) <= (today.year, today.month):
        yield f"{y:04d}-{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def download(month: str) -> str:
    name = f"fhvhv_tripdata_{month}.parquet"
    dest = RAW / name
    if dest.exists() and dest.stat().st_size > 0:
        return "exists"
    url = f"{CDN}/{name}"
    with requests.get(url, stream=True, timeout=300) as r:
        if r.status_code == 403 or r.status_code == 404:
            return "not-published"
        r.raise_for_status()
        tmp = dest.with_suffix(".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
        tmp.rename(dest)
    return f"{dest.stat().st_size / 1e6:.0f} MB"


if __name__ == "__main__":
    missing_streak = 0
    for month in months_from(START):
        for attempt in range(3):
            try:
                status = download(month)
                break
            except Exception as e:
                print(f"{month}: retry {attempt + 1} ({e})", flush=True)
                time.sleep(15 * (attempt + 1))
        else:
            status = "failed"
        print(f"{month}: {status}", flush=True)
        if status == "not-published":
            missing_streak += 1
            if missing_streak >= 3:
                print("reached unpublished months, stopping")
                break
        else:
            missing_streak = 0
    total = sum(f.stat().st_size for f in RAW.glob("*.parquet"))
    print(f"total on disk: {total / 1e9:.1f} GB, "
          f"{len(list(RAW.glob('*.parquet')))} files")
