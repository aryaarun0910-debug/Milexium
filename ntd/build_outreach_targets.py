"""Generate a prioritized, personalized outreach target list from NTD data.

Tiering logic (who takes a pilot call from a two-founder startup):
- Tier A: 50k to 1M annual trips. Big enough that savings are real money,
  small enough that the ops director picks their own software.
- Tier B: 20k to 50k trips. County programs, quick decisions, smaller ACV.
- Tier C: over 1M trips. Brand-name proof targets, longest sales cycle.

Every row carries a hook sentence built ONLY from the agency's own NTD
filing, so outreach reads researched rather than blasted.

Output: outreach/targets_ntd.csv (top 80 by tier then trips)
"""

from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
OUTDIR = HERE.parent / "outreach"
OUTDIR.mkdir(exist_ok=True)

df = pd.read_csv(HERE / "agency_economics.csv")
df = df[df.trips >= 20_000].copy()

MEDIAN_CPT = df[df.report_year == 2024].cost_per_trip.median()


def tier(trips: float) -> str:
    if trips >= 1_000_000:
        return "C"
    if trips >= 50_000:
        return "A"
    return "B"


def hook(r) -> str:
    parts = [f"Your NTD {r.report_year} filing reports {r.trips:,.0f} "
             f"demand-response trips at ${r.cost_per_trip:,.2f} per trip"]
    if pd.notna(r.deadhead_pct_hours) and r.deadhead_pct_hours > 0:
        parts.append(
            f", with {r.deadhead_pct_hours:.0%} of vehicle hours spent "
            f"deadheading. A 10 percent deadhead reduction is worth about "
            f"${r.value_10pct_deadhead_cut:,.0f} a year to you.")
    elif r.cost_per_trip > MEDIAN_CPT:
        parts.append(
            f". The national median is ${MEDIAN_CPT:,.2f}; closing even a "
            f"quarter of that gap is worth about "
            f"${0.25 * (r.cost_per_trip - MEDIAN_CPT) * r.trips:,.0f} a year.")
    else:
        parts.append(
            f". You already run leaner than the ${MEDIAN_CPT:,.2f} national "
            f"median; we would like to learn what you do well and show you "
            f"where trip-level explanations still save hours of dispute "
            f"handling.")
    return "".join(parts)


df["tier"] = df.trips.apply(tier)
df["hook"] = df.apply(hook, axis=1)

cols = ["tier", "agency", "city", "state", "report_year", "trips",
        "cost_per_trip", "deadhead_pct_hours", "value_10pct_deadhead_cut",
        "vehicles", "organization_type", "hook"]
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
