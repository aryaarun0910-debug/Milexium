"""Bulk-download NYC TLC Yellow and Green taxi trip parquet.

Complements the FHVHV (Uber/Lyft) corpus with the two classic taxi
modalities, which reach back to 2009 (yellow) and 2013 (green) - far
deeper history than FHVHV's 2019 start, and a structurally different
demand pattern (street-hail vs app-dispatch). All three together give the
pretraining corpus multiple real NYC demand regimes across 15+ years.

Files land in realdata/raw_tlc_taxi/ (gitignored). Resumable: skips files
already on disk, so it continues cleanly after a shutdown. Yellow monthly
files run ~30-60 MB (recent) to several hundred MB (2010-2015 peak taxi
era); green are smaller.

Usage:
  py -3 realdata/fetch_tlc_yellow_green.py            # yellow 2011-, green 2014-
  py -3 realdata/fetch_tlc_yellow_green.py 2015-01    # start from a given month
"""

import sys
import time
from datetime import date
from pathlib import Path

import requests

RAW = Path(__file__).parent / "raw_tlc_taxi"
RAW.mkdir(parents=True, exist_ok=True)

CDN = "https://d37ci6vzurychx.cloudfront.net/trip-data"
START = sys.argv[1] if len(sys.argv) > 1 else "2011-01"

# (prefix, first-published-month) - the CDN only has files from these dates.
FEEDS = [("yellow_tripdata", "2011-01"), ("green_tripdata", "2014-01")]


def months_from(start: str):
    y, m = map(int, start.split("-"))
    today = date.today()
    while (y, m) <= (today.year, today.month):
        yield f"{y:04d}-{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


class RateLimited(Exception):
    """CloudFront 403 = throttled after too many rapid requests. This is
    NOT the same as 404 (file genuinely not published). Earlier this bug
    made the fetcher treat a 403 as 'not-published' and permanently give
    up on green taxi + yellow 2024+ after 155 rapid yellow downloads
    tripped the throttle. 403 must back off and retry, only 404 means stop."""


def download(prefix: str, month: str) -> str:
    name = f"{prefix}_{month}.parquet"
    dest = RAW / name
    if dest.exists() and dest.stat().st_size > 0:
        return "exists"
    url = f"{CDN}/{name}"
    with requests.get(url, stream=True, timeout=300) as r:
        if r.status_code == 404:
            return "not-published"
        if r.status_code == 403:
            raise RateLimited(f"403 throttled on {name}")
        r.raise_for_status()
        tmp = dest.with_suffix(".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
        tmp.rename(dest)
    return f"{dest.stat().st_size / 1e6:.0f} MB"


if __name__ == "__main__":
    for prefix, feed_start in FEEDS:
        start = max(START, feed_start)
        missing_streak = 0
        for month in months_from(start):
            # Up to 6 attempts with escalating backoff: a 403 throttle can
            # take a couple of minutes to clear, so back off longer on 403.
            for attempt in range(6):
                try:
                    status = download(prefix, month)
                    break
                except RateLimited as e:
                    wait = min(120, 20 * (attempt + 1))
                    print(f"{prefix} {month}: {e}, backing off {wait}s",
                          flush=True)
                    time.sleep(wait)
                except Exception as e:
                    print(f"{prefix} {month}: retry {attempt + 1} ({e})",
                          flush=True)
                    time.sleep(15 * (attempt + 1))
            else:
                status = "failed"
            print(f"{prefix} {month}: {status}", flush=True)
            if status == "not-published":
                missing_streak += 1
                if missing_streak >= 3:
                    print(f"{prefix}: reached unpublished months, moving on")
                    break
            else:
                missing_streak = 0
            # polite pacing between downloads to avoid tripping the throttle
            time.sleep(1.5)
    total = sum(f.stat().st_size for f in RAW.glob("*.parquet"))
    print(f"total on disk: {total / 1e9:.1f} GB, "
          f"{len(list(RAW.glob('*.parquet')))} files", flush=True)
