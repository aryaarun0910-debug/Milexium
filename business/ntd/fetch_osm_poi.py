"""Pull real medical/senior/dialysis facility locations from OpenStreetMap.

Replaces the fictional reference agency's guessed zone flags (has_dialysis,
has_daycenter, has_medical in business/reference_agency/generate_trips.py) with real
geography. Any US county can get this, not just the two cities we have
event-level trip data for, so it's a scalable feature source for any
outreach target in business/ntd/agency_economics.csv.

Overpass API needs no key. One query per target county (by name, resolved
to a bounding area via Nominatim-style area lookup inside the Overpass
query itself), rate-limited to be a polite public-API citizen.

Output: business/ntd/osm_poi/<county_slug>.csv
  columns: category, name, lat, lon, osm_type, osm_id
"""

import argparse
import time
from pathlib import Path

import pandas as pd
import requests

OUT = Path(__file__).parent / "osm_poi"
OUT.mkdir(exist_ok=True)
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Both OSM public services 406/block requests with no identifying
# User-Agent, and their usage policies ask for one.
HEADERS = {"User-Agent": "Milexium-research/1.0 (contact: aryaarun0910@gmail.com)"}


def county_bbox(county: str, state: str) -> tuple[float, float, float, float]:
    """Geocode a county to a bounding box via Nominatim: far cheaper for the
    shared Overpass instance than an in-query administrative-boundary
    regex search, which times out on large/complex counties."""
    params = {"q": f"{county} County, {state}, USA", "format": "json",
              "limit": 1}
    r = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    results = r.json()
    if not results:
        raise ValueError(f"Nominatim found nothing for {county}, {state}")
    s, n, w, e = (float(x) for x in results[0]["boundingbox"])
    return s, w, n, e  # Overpass bbox order: south,west,north,east

# category -> OSM tag filters (nwr = node/way/relation)
TAG_FILTERS = {
    "dialysis": ['["healthcare"="dialysis"]', '["amenity"="dialysis"]'],
    "senior_center": ['["social_facility"="senior_center"]',
                       '["amenity"="social_facility"]["social_facility:for"="senior"]'],
    "adult_day_program": ['["social_facility"="day_care"]["social_facility:for"~"senior|disabled"]'],
    "hospital": ['["amenity"="hospital"]'],
    "nursing_home": ['["amenity"="nursing_home"]', '["social_facility"="nursing_home"]'],
}


def query_one_category(bbox_str: str, tags: list[str]) -> list[dict]:
    """One category per request: the combined multi-category county-wide
    query timed out on the shared public Overpass instance even with a
    bbox filter; single-tag requests over the same bbox return in
    seconds, so we pay in request count instead of per-request weight."""
    filters = "".join(f'nwr{tag}({bbox_str});' for tag in tags)
    body = f"[out:json][timeout:60];({filters});out center;"
    r = requests.post(OVERPASS_URL, data={"data": body}, headers=HEADERS,
                       timeout=90)
    r.raise_for_status()
    payload = r.json()
    if "remark" in payload and not payload.get("elements"):
        raise RuntimeError(payload["remark"])
    return payload.get("elements", [])


def query_county(county: str, state: str) -> pd.DataFrame:
    bbox = county_bbox(county, state)
    bbox_str = ",".join(str(x) for x in bbox)

    els = []
    for cat, tags in TAG_FILTERS.items():
        els.extend(query_one_category(bbox_str, tags))
        time.sleep(2)

    rows = []
    for el in els:
        tags = el.get("tags", {})
        name = tags.get("name", "unnamed")
        if tags.get("healthcare") == "dialysis" or tags.get("amenity") == "dialysis":
            cat = "dialysis"
        elif tags.get("social_facility") == "senior_center":
            cat = "senior_center"
        elif tags.get("social_facility") == "day_care":
            cat = "adult_day_program"
        elif tags.get("amenity") == "hospital":
            cat = "hospital"
        elif tags.get("amenity") == "nursing_home" or tags.get("social_facility") == "nursing_home":
            cat = "nursing_home"
        else:
            cat = "other"
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None:
            continue
        rows.append({"category": cat, "name": name, "lat": lat, "lon": lon,
                     "osm_type": el["type"], "osm_id": el["id"]})
    df = pd.DataFrame(rows).drop_duplicates(subset=["osm_type", "osm_id"])
    df.insert(0, "county", county)
    df.insert(1, "state", state)
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("counties", nargs="+",
                     help="pairs of 'County Name,ST' e.g. 'Cook,IL' 'Kings,NY'")
    args = ap.parse_args()

    for spec in args.counties:
        county, state = [s.strip() for s in spec.split(",")]
        slug = f"{county.lower().replace(' ', '_')}_{state.lower()}"
        dest = OUT / f"{slug}.csv"
        if dest.exists():
            print(f"{spec}: already have {dest}")
            continue
        try:
            df = query_county(county, state)
            df.to_csv(dest, index=False)
            print(f"{spec}: {len(df)} facilities -> {dest}")
        except Exception as e:
            print(f"{spec}: failed ({e})")
        time.sleep(3)  # polite pacing on the shared public Overpass instance
