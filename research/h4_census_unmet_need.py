"""H4 -- does ADA-eligible population explain demand-response volume?

Run:  py -3 research/h4_census_unmet_need.py

The politically-important version of the cost story. If some agencies serve far
below what their disabled population implies, the finding is UNMET NEED, not
inefficiency -- and unmet need points the opposite way politically, which the
brief says matters because our audience rejects framing efficiency as serving
fewer riders.

Geography
---------
NTD carries `UACE Code`, which IS the Census urbanized-area code. So this is an
EXACT geographic join, not a name match. ACS 2023 5-year, `for=urban area:*`,
2020 urban-area vintage -- the same vintage NTD's UACE codes use (the OPEX file
declares `Census Year = 2020`).

Unit of analysis
----------------
The honest unit is the URBANIZED AREA, not the agency: several operators can
serve one UZA, and dividing one operator's trips by the whole UZA's disabled
population understates it. Both are computed; the agency-level view is tagged
with how many DR operators share its UZA so the contamination is visible rather
than hidden.

Tables
------
B18101 Sex by Age by Disability Status -> total civilian noninstitutionalised
       population and total with any disability.
B18105 Sex by Age by Ambulatory Difficulty -> the closest ACS proxy for the
       population ADA complementary paratransit exists to serve. Not the same
       as ADA eligibility (which is a functional determination about using
       fixed route, not a diagnosis) -- stated, not glossed.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib import env, median, pct, pearson, say, spearman  # noqa: E402

ACS = "https://api.census.gov/data/2023/acs/acs5"
CACHE = HERE / "acs_urban_area_disability.json"

DIS = [
    "B18101_004E", "B18101_007E", "B18101_010E", "B18101_013E",
    "B18101_016E", "B18101_019E", "B18101_023E", "B18101_026E",
    "B18101_029E", "B18101_032E", "B18101_035E", "B18101_038E",
]
# 65+ with a disability (male 65-74, 75+; female 65-74, 75+)
DIS65 = ["B18101_016E", "B18101_019E", "B18101_035E", "B18101_038E"]


def fetch(varlist):
    key = env("CENSUS_API_KEY")
    url = f"{ACS}?get=NAME,{','.join(varlist)}&for=urban%20area:*"
    if key:
        url += f"&key={key}"
    with urllib.request.urlopen(url, timeout=180) as r:
        return json.loads(r.read().decode())


def ambulatory_vars():
    with urllib.request.urlopen(f"{ACS}/groups/B18105.json", timeout=90) as r:
        g = json.loads(r.read().decode())["variables"]
    return sorted(
        v
        for v, m in g.items()
        if v.endswith("E") and "With an ambulatory difficulty" in m["label"]
    )


def load_acs():
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    amb = ambulatory_vars()
    say(f"ambulatory-difficulty cells: {len(amb)}")
    rows = {}
    for chunk in (["B18101_001E"] + DIS, amb):
        data = fetch(chunk)
        head = data[0]
        for rec in data[1:]:
            d = dict(zip(head, rec))
            uace = d["urban area"]
            rows.setdefault(uace, {"NAME": d["NAME"]})
            for v in chunk:
                try:
                    rows[uace][v] = float(d[v])
                except (TypeError, ValueError):
                    rows[uace][v] = None
    out = {}
    for uace, d in rows.items():
        dis = sum(d.get(v) or 0 for v in DIS)
        dis65 = sum(d.get(v) or 0 for v in DIS65)
        ambt = sum(d.get(v) or 0 for v in amb)
        out[uace] = {
            "name": d["NAME"],
            "pop_civ_noninst": d.get("B18101_001E"),
            "disability_any": dis,
            "disability_65plus": dis65,
            "ambulatory_difficulty": ambt,
        }
    CACHE.write_text(json.dumps(out), encoding="utf-8")
    say(f"cached {len(out)} urban areas -> {CACHE.name}")
    return out


def main() -> None:
    acs = load_acs()
    say(f"ACS urban areas: {len(acs)}")

    panel = json.loads((HERE / "dr_panel.json").read_text(encoding="utf-8"))
    # UACE code lives in the OPEX metadata; re-read it from the panel build's
    # source so the join key is the same bytes NTD published.
    import csv

    from lib import OPEX

    uace_of = {}
    for row in csv.DictReader(open(OPEX, newline="", encoding="utf-8-sig")):
        uace_of.setdefault(row["NTD ID"], row["UACE Code"])

    YEAR = 2023  # ACS 2019-2023 5-year centres on 2021; 2023 NTD is the closest
    rows = [r for r in panel if r["year"] == YEAR]
    say(f"DR agency-years in {YEAR}: {len(rows)}")

    matched, unmatched = [], 0
    uza_agencies = defaultdict(list)
    for r in rows:
        u = (uace_of.get(r["ntd_id"]) or "").strip().zfill(5)
        a = acs.get(u)
        if not a or not a["ambulatory_difficulty"]:
            unmatched += 1
            continue
        r = dict(r, uace=u, uza_acs=a)
        matched.append(r)
        uza_agencies[u].append(r)

    say(f"joined to a Census urban area: {len(matched)}   unmatched: {unmatched}")
    say(f"distinct urbanized areas covered: {len(uza_agencies)}")
    multi = sum(1 for v in uza_agencies.values() if len(v) > 1)
    say(
        f"UZAs with more than one DR operator: {multi} "
        f"({100*multi/len(uza_agencies):.0f}%) -- agency-level rates are "
        f"contaminated in exactly these"
    )

    # ---- UZA-level: the clean unit ---------------------------------------
    import math

    uza = []
    for u, rs in uza_agencies.items():
        a = rs[0]["uza_acs"]
        upt = sum(r["upt"] for r in rs)
        opex = sum(r["opex_2024usd"] for r in rs)
        uza.append(
            {
                "uace": u,
                "name": a["name"],
                "n_operators": len(rs),
                "dr_upt": upt,
                "dr_opex_2024usd": opex,
                "pop": a["pop_civ_noninst"],
                "disability_any": a["disability_any"],
                "disability_65plus": a["disability_65plus"],
                "ambulatory": a["ambulatory_difficulty"],
                "trips_per_ambulatory_person": upt / a["ambulatory_difficulty"],
                "trips_per_disabled_person": upt / a["disability_any"]
                if a["disability_any"]
                else None,
                "disability_rate": a["disability_any"] / a["pop_civ_noninst"]
                if a["pop_civ_noninst"]
                else None,
            }
        )
    uza = [u for u in uza if u["dr_upt"] > 0 and u["ambulatory"] > 0]
    say(f"\nUZA-level rows usable: {len(uza)}")

    lx = [math.log(u["ambulatory"]) for u in uza]
    ly = [math.log(u["dr_upt"]) for u in uza]
    lpop = [math.log(u["pop"]) for u in uza]
    say("\n[1] Does disabled population explain DR volume? (UZA level, log-log)")
    say(f"    corr(log ambulatory-difficulty pop, log DR trips) r = {pearson(lx,ly):.3f}  "
        f"R2 = {pearson(lx,ly)**2:.3f}   (Spearman {spearman(lx,ly):.3f})")
    say(f"    corr(log TOTAL population,          log DR trips) r = {pearson(lpop,ly):.3f}  "
        f"R2 = {pearson(lpop,ly)**2:.3f}")

    # elasticity
    from lib import ols

    beta, r2 = ols([[v] for v in lx], ly)
    say(f"    OLS log DR trips ~ log ambulatory pop:  elasticity = {beta[1]:.3f}, R2 = {r2:.3f}")

    rates = [u["trips_per_ambulatory_person"] for u in uza]
    say("\n[2] Service intensity: DR trips per person with ambulatory difficulty/yr")
    for p in (5, 10, 25, 50, 75, 90, 95):
        say(f"      p{p:<3} {pct(rates,p):8.2f}")
    say(f"      max  {max(rates):8.2f}   min {min(rates):8.4f}")
    say(f"      ratio p90/p10 = {pct(rates,90)/pct(rates,10):.1f}x")

    uza.sort(key=lambda u: u["trips_per_ambulatory_person"])
    say("\n[3] Lowest service intensity, UZAs with >=100,000 ambulatory-difficulty pop:")
    big = [u for u in uza if u["ambulatory"] >= 100000]
    say(f"    (n={len(big)} such UZAs)")
    for u in big[:12]:
        say(
            f"      {u['name'][:46]:<47}{u['trips_per_ambulatory_person']:8.2f}"
            f"  amb_pop={u['ambulatory']:>9,.0f}  DR trips={u['dr_upt']:>11,.0f}"
            f"  ops={u['n_operators']}"
        )
    say("\n    Highest service intensity among the same group:")
    for u in big[::-1][:8]:
        say(
            f"      {u['name'][:46]:<47}{u['trips_per_ambulatory_person']:8.2f}"
            f"  amb_pop={u['ambulatory']:>9,.0f}  DR trips={u['dr_upt']:>11,.0f}"
            f"  ops={u['n_operators']}"
        )

    # ---- [4] does low intensity co-occur with high cost? -----------------
    say("\n[4] Is low service intensity the same thing as high cost per trip?")
    cpt = []
    inten = []
    for u in uza:
        if u["dr_upt"] > 0:
            cpt.append(u["dr_opex_2024usd"] / u["dr_upt"])
            inten.append(u["trips_per_ambulatory_person"])
    say(f"    Spearman(cost per trip, trips per ambulatory person) = {spearman(cpt,inten):.3f}")
    say(f"    Pearson(log cpt, log intensity) = "
        f"{pearson([math.log(c) for c in cpt],[math.log(i) for i in inten]):.3f}")

    out = {
        "acs_vintage": "ACS 2019-2023 5-year, urban area (2020 vintage)",
        "ntd_year": YEAR,
        "n_uza": len(uza),
        "n_agency_years_joined": len(matched),
        "n_unmatched": unmatched,
        "uza_multi_operator_pct": 100 * multi / len(uza_agencies),
        "elasticity_dr_trips_wrt_ambulatory_pop": beta[1],
        "r2_loglog": r2,
        "r_ambulatory": pearson(lx, ly),
        "r_total_pop": pearson(lpop, ly),
        "intensity_percentiles": {f"p{p}": pct(rates, p) for p in (5, 10, 25, 50, 75, 90, 95)},
        "spearman_cpt_vs_intensity": spearman(cpt, inten),
        "uza_rows": uza,
    }
    (HERE / "h4_census_unmet_need.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    say("\nwrote research/h4_census_unmet_need.json")


if __name__ == "__main__":
    main()
