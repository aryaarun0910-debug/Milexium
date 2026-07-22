"""Render demo assets from REAL data, replacing the two synthetic-pipeline
assets that are honestly rebuildable with what we actually have.

Of the five original artifacts/demo-assets/*.png (from
reference_agency/make_demo_assets.py),
only two are pure demand-FORECASTING visualizations: why_this_forecast.png
(a SHAP explanation) and demand_curve.png (predicted vs actual). Those get
real-data replacements here, sourced from realdata/explanations_aar.json
and realdata/output/aar_valid.csv.gz -- both already computed from the real
AAR model on real bookings, not synthetic ones.

The other three (why_this_trip, capacity_alert, fleet_timeline) depend on
individual-trip-level SCHEDULING decisions. No public paratransit dataset
provides trip-level records, so those stay on the synthetic pipeline until
real pilot data exists -- see reference_agency/README.md honesty note 5. Do not
try to force those to "real" here; that would mean fabricating fake trip
records, which is worse than being honest about the gap.

Output: artifacts/demo-assets/why_this_forecast_real.png, demand_curve_real.png
(new files, not overwriting the synthetic originals, so both the
forecasting-only real assets and the full synthetic five-asset set stay
available side by side until the scheduler has a real trip stream too).
"""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import FancyBboxPatch

HERE = Path(__file__).parent
ASSETS = HERE.parent / "artifacts" / "demo-assets"
ASSETS.mkdir(parents=True, exist_ok=True)

SURFACE, INK, INK2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984"
BLUE, AQUA, VIOLET, RED, ORANGE = "#2a78d6", "#1baf7a", "#4a3aa7", "#e34948", "#eb6834"

plt.rcParams.update({
    "font.family": ["Segoe UI", "DejaVu Sans"],
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "axes.edgecolor": "#d8d7d2", "axes.linewidth": 0.8,
    "axes.grid": True, "grid.color": "#e8e7e2", "grid.linewidth": 0.6,
    "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.labelcolor": INK2,
    "savefig.dpi": 200, "savefig.facecolor": SURFACE,
})
BRAND = "Milexium"


def card_frame(ax):
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    ax.add_patch(FancyBboxPatch((0.01, 0.02), 0.98, 0.96,
                 boxstyle="round,pad=0.012,rounding_size=0.025",
                 fc="white", ec="#e2e1dc", lw=1.2))


# ---------------------------- 1. "Why this forecast" from real SHAP output
expl = json.loads((HERE / "explanations_aar.json").read_text())
# pick the example with the most distinct top factors for a legible chart
ex = max(expl["example_explanations"], key=lambda e: len(e["top_factors"]))
factors = sorted(ex["top_factors"], key=lambda f: abs(f["shap"]))

fig, ax = plt.subplots(figsize=(7.4, 4.2))
names = [f["label"] for f in factors]
vals = [f["shap"] for f in factors]
colors = [BLUE if v >= 0 else ORANGE for v in vals]
bars = ax.barh(names, vals, color=colors, height=0.52, zorder=3)
span = max(vals) - min(0, min(vals))
pad = max(span * 0.06, 0.015)
for b, v in zip(bars, vals):
    ax.text(v + (pad if v >= 0 else -pad), b.get_y() + b.get_height() / 2,
            f"{v:+.2f}", va="center", ha="left" if v >= 0 else "right",
            fontsize=8.5, color=INK2)
ax.set_xlim(min(0, min(vals)) - pad * 5, max(vals) + pad * 5)
ax.axvline(0, color="#c8c7c2", lw=1, zorder=2)
ax.set_xlabel("SHAP contribution (Poisson log-rate space; direction and rank\n"
              "are valid, values do not sum linearly in booking units)",
              fontsize=8)
ax.set_title(
    f"Why this forecast (real data):  {ex['zone']}, {ex['date']} {ex['hour']:02d}:00  "
    f"→  {ex['predicted_bookings']:.0f} bookings predicted, "
    f"{ex['actual_bookings']} observed",
    fontsize=10.5, loc="left", pad=12, color=INK)
ax.grid(axis="y", visible=False)
ax.spines[["top", "right", "left"]].set_visible(False)
fig.text(0.985, 0.015, f"{BRAND}  ·  real NYC Access-A-Ride model, not synthetic",
         fontsize=7.5, color=MUTED, ha="right", style="italic")
fig.tight_layout()
fig.savefig(ASSETS / "why_this_forecast_real.png", bbox_inches="tight")
plt.close(fig)


# --------------------------- 2. Predicted vs actual, real AAR, with interval
valid = pd.read_csv(HERE / "output" / "aar_valid.csv.gz", parse_dates=["date"])
# pick the borough-day with the highest observed volume for a legible curve
best = (valid.groupby(["date", "borough"]).y.sum()
        .sort_values(ascending=False).index[0])
day, borough = best
dv = valid[(valid.date == day) & (valid.borough == borough)].sort_values("hour")

fig, ax = plt.subplots(figsize=(7.4, 3.8))
ax.fill_between(dv.hour, dv.lo, dv.hi, color=BLUE, alpha=0.12, zorder=2,
                label="90% conformal interval")
ax.plot(dv.hour, dv.y, color="#9b9a95", lw=2, marker="o", ms=4, zorder=4,
        label="Observed bookings")
ax.plot(dv.hour, dv.pred, color=BLUE, lw=2, marker="o", ms=4, zorder=5,
        label="Milexium forecast")
ax.plot(dv.hour, dv.naive, color=MUTED, lw=1.3, ls="--", zorder=3,
        label="Seasonal-naive baseline")
ax.set_xlim(-0.5, 23.5)
ax.set_xticks(range(0, 24, 2))
ax.set_xticklabels([f"{h:02d}:00" for h in range(0, 24, 2)], fontsize=8)
ax.set_ylabel("Access-A-Ride bookings per hour")
ax.set_title(
    f"Real demand forecast vs observed, {borough}, {day:%a %d %b %Y} "
    f"(untouched holdout window)", fontsize=10.5, loc="left", pad=10)
ax.legend(frameon=False, fontsize=8, loc="upper right")
ax.grid(axis="x", visible=False)
ax.spines[["top", "right"]].set_visible(False)
fig.text(0.985, 0.02, f"{BRAND}  ·  real NYC Access-A-Ride data, not synthetic",
         fontsize=7.5, color=MUTED, ha="right", style="italic")
fig.tight_layout()
fig.savefig(ASSETS / "demand_curve_real.png", bbox_inches="tight")
plt.close(fig)

print("real-data demo assets written to", ASSETS)
for p in ("why_this_forecast_real.png", "demand_curve_real.png"):
    print(" -", p)
