"""Generate a prioritized, personalized outreach target list from NTD data.

Tiering logic (who takes a pilot call from a two-founder startup):
- Tier A: 50k to 1M annual trips. Big enough to run a real scheduling
  operation, small enough that the ops director picks their own software.
- Tier B: 20k to 50k trips. County programs, quick decisions, smaller ACV.
- Tier C: over 1M trips. Brand-name proof targets, longest sales cycle.

Every row carries a hook sentence built ONLY from the agency's own NTD filing
and its position in the national panel, so outreach reads researched rather
than blasted.

THE HOOK IS A POSITION, NOT A DOLLAR FIGURE
-------------------------------------------
This file used to write two savings claims into every hook: "a 10 percent
deadhead reduction is worth about $X a year to you", and for agencies with no
deadhead detail, "closing even a quarter of that gap [to the national median
cost per trip] is worth about $X a year". BOTH ARE REMOVED (packet
MX-CLAIMS-DOLLAR-SWEEP-013).

- The first assumed a high deadhead figure means a recoverable cost problem.
  It does not: Pearson +0.017, OLS R2 0.0003 on n=405
  (research/h5b_structure_vs_cost.json); Spearman +0.024 over 406 operators
  against +0.738 for cost per HOUR, cost per trip flat at $48.53 in the lowest
  deadhead quartile against $54.09 in the highest
  (outreach/panel_findings.json, `dr_deadhead_predicts_cost_per_trip`,
  REJECTED by the panel gate on effect size).
- The second was worse. It assumed the cost gap to the median is RECOVERABLE,
  which is exactly the causal claim the platform refuses to make elsewhere:
  packages/replay/teardown.py will not emit a savings envelope without the
  operator's own fixed/variable split.

What replaces both is where the operator sits nationally on cost per trip,
cost per revenue hour and trips per revenue hour. True, checkable against
their own books, invisible from inside their own data, and it values nothing.

Output: outreach/targets_ntd.csv (top 80 by tier then trips)
"""

from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
OUTDIR = HERE.parent / "outreach"
OUTDIR.mkdir(exist_ok=True)

econ = pd.read_csv(HERE / "agency_economics.csv")

# The comparison panel is EVERY 2024 filer, and is taken before the targeting
# filter below. Previously the "national median" quoted back to an agency was
# computed after `trips >= 20_000`, i.e. it was the median of mid-size and
# larger operators described to the reader as national ($36.61 against a true
# national $37.97). A number presented as national has to be national.
PANEL = econ[econ.report_year == 2024]

df = econ[econ.trips >= 20_000].copy()
MEDIAN_CPT = PANEL.cost_per_trip.median()
MEDIAN_CPH = PANEL.cost_per_vrh.median()
MEDIAN_TPH = PANEL.trips_per_vrh.median()


def tier(trips: float) -> str:
    if trips >= 1_000_000:
        return "C"
    if trips >= 50_000:
        return "A"
    return "B"


def _pctile(series, value) -> float:
    """Percentile of one operator within the 2024 national panel."""
    s = series.dropna()
    return float((s < value).mean() * 100)


def hook(r) -> str:
    """Their national position, from their own filing. No dollar valuation.

    Cost per HOUR leads because it is the variable that actually ranks with
    cost per trip (Spearman +0.738 across 406 operators), where deadhead share
    ranks at +0.024 -- outreach/panel_findings.json.
    """
    parts = [f"Your NTD {r.report_year} filing reports {r.trips:,.0f} "
             f"demand-response trips at ${r.cost_per_trip:,.2f} per trip, "
             f"which is percentile {_pctile(PANEL.cost_per_trip, r.cost_per_trip):.0f} "
             f"of the {len(PANEL):,} US demand-response operators filing for "
             f"2024 (national median ${MEDIAN_CPT:,.2f})."]
    if pd.notna(r.cost_per_vrh) and pd.notna(r.trips_per_vrh):
        parts.append(
            f" Underneath that: ${r.cost_per_vrh:,.2f} per revenue hour "
            f"(median ${MEDIAN_CPH:,.2f}) and {r.trips_per_vrh:,.2f} trips per "
            f"revenue hour (median {MEDIAN_TPH:,.2f}). Roughly half the "
            f"national spread in cost per trip is the price of an hour and "
            f"roughly half is how many trips fit into one, and only the second "
            f"is anything a scheduler sets.")
    parts.append(
        " That is a position, not a diagnosis, and it is not a number we can "
        "tell you is recoverable. What we would want to work out with you is "
        "which half of it you are actually looking at.")
    return "".join(parts)


df["tier"] = df.trips.apply(tier)
df["hook"] = df.apply(hook, axis=1)

cols = ["tier", "agency", "city", "state", "report_year", "trips",
        "cost_per_trip", "cost_per_vrh", "trips_per_vrh",
        "deadhead_pct_hours", "vehicles", "organization_type", "hook"]
out = (df[cols]
       .sort_values(["tier", "trips"], ascending=[True, False])
       .groupby("tier", group_keys=False).head(40))
out = pd.concat([
    out[out.tier == "A"].head(40),
    out[out.tier == "B"].head(25),
    out[out.tier == "C"].head(15),
])
out.to_csv(OUTDIR / "targets_ntd.csv", index=False)
print(f"saved outreach/targets_ntd.csv: {len(out)} targets "
      f"(A: {(out.tier == 'A').sum()}, B: {(out.tier == 'B').sum()}, "
      f"C: {(out.tier == 'C').sum()})")
print(out[["agency", "state", "trips", "cost_per_trip"]].head(8).to_string())
