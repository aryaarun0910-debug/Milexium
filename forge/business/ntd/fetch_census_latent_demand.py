"""Pull Census ACS 5-year data: a latent-mobility-need proxy layer.

Every NTD number so far describes CURRENT ridership. This pulls a proxy for
population that MAY have mobility needs regardless of current ridership:
county-level share of residents 65+, share with a disability, and share of
households with no vehicle available. This is NOT an ADA-paratransit-eligible
headcount: 49 CFR Part 37 Subpart F defines eligibility by functional
inability to use fixed-route service (and is often trip-specific), not by
age or disability status alone; age in particular is explicitly not a
qualifying criterion. Treat these figures as a directional latent-need
signal for market sizing and outreach framing ("your county has N residents
who are 65+ or report a disability, a population segment worth understanding
even though it is not the same as your ADA-eligible ridership base"), never
as a legal eligibility count.

Source: ACS 5-year Data Profile, 2023 vintage, table DP02/DP04/DP05, county
geography (best match to how most demand-response agencies define service
area). Variables confirmed against api.census.gov/data/2023/acs/acs5/
profile/variables.json before use, not guessed.

Output: forge/business/ntd/census_latent_demand.csv
  columns: state_fips, county_fips, county_name, total_population,
           pct_65_plus, pct_disability, disability_count,
           pct_no_vehicle_household, no_vehicle_household_count
"""

import os
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).parent
YEAR = 2023
VARS = {
    "DP05_0001E": "total_population",
    "DP05_0024PE": "pct_65_plus",
    "DP02_0072PE": "pct_disability",
    "DP02_0072E": "disability_count",
    "DP04_0058PE": "pct_no_vehicle_household",
    "DP04_0058E": "no_vehicle_household_count",
    "NAME": "county_name",
}

def _load_dotenv_key(name: str) -> str | None:
    """Tiny inline .env reader so this works with no extra dependency."""
    env_path = HERE.parents[2] / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip()
    return None


CENSUS_API_KEY = os.environ.get("CENSUS_API_KEY") or _load_dotenv_key("CENSUS_API_KEY")
if not CENSUS_API_KEY:
    raise SystemExit(
        "Set CENSUS_API_KEY (free, instant signup at "
        "api.census.gov/data/key_signup.html), either as an environment "
        "variable or a CENSUS_API_KEY=... line in the repo's .env file.")

url = f"https://api.census.gov/data/{YEAR}/acs/acs5/profile"
params = {
    "get": ",".join(VARS.keys()),
    "for": "county:*",
    "in": "state:*",
    "key": CENSUS_API_KEY,
}
r = requests.get(url, params=params, timeout=120)
r.raise_for_status()
rows = r.json()
df = pd.DataFrame(rows[1:], columns=rows[0])
df = df.rename(columns=VARS)
df = df.rename(columns={"state": "state_fips", "county": "county_fips"})

numeric_cols = [v for k, v in VARS.items() if k != "NAME"]
for c in numeric_cols:
    df[c] = pd.to_numeric(df[c], errors="coerce")

df = df[["state_fips", "county_fips", "county_name"] + numeric_cols]
df.to_csv(HERE / "census_latent_demand.csv", index=False)
print(f"saved forge/business/ntd/census_latent_demand.csv: {len(df)} counties")
print(df.sort_values("total_population", ascending=False)
      [["county_name", "total_population", "pct_65_plus", "pct_disability",
        "pct_no_vehicle_household"]].head(8).to_string(index=False))
