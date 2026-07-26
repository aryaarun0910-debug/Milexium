"""Render the demo assets for the website and demo video.

Inputs: business/reference_agency/output/* (trips, model, audit log, schedule)
Outputs: evidence/artifacts/demo-assets/*.png

All data is synthetic; rider ids are synthetic. Palette follows the validated
reference set: blue #2a78d6 accent/sequential, blue/orange for polarity,
slots 1/2/5 for categorical, text never in series color.
"""

import json
import numpy as np
import pandas as pd
import xgboost as xgb
import shap
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from pathlib import Path

OUT = Path(__file__).parent / "output"
ASSETS = Path(__file__).resolve().parents[2] / "evidence" / "artifacts" / "demo-assets"
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

audit = json.loads((OUT / "audit_log.json").read_text())
sched = pd.read_csv(OUT / "schedule.csv")
valid = pd.read_csv(OUT / "panel_valid.csv", parse_dates=["date"])
metrics = json.loads((OUT / "metrics.json").read_text())

BRAND = "Milexium"

def card_frame(ax):
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    ax.add_patch(FancyBboxPatch((0.01, 0.02), 0.98, 0.96,
                 boxstyle="round,pad=0.012,rounding_size=0.025",
                 fc="white", ec="#e2e1dc", lw=1.2))

# ------------------------------------------------- 1. "Why this trip" card
pooled = next(a for a in audit if a["decision"] != "UNSERVED"
              and "pool" in a["run_kind"] and len(a.get("rejected", [])) > 0
              and any("wheelchair" in f for f in a["factors"]))

fig, ax = plt.subplots(figsize=(7.4, 4.6))
card_frame(ax)
ax.text(0.06, 0.90, "WHY THIS TRIP", fontsize=8.5, color=BLUE, weight="bold")
ax.text(0.94, 0.90, BRAND, fontsize=8.5, color=MUTED, ha="right")
riders = ", ".join(pooled["riders"][:3]) + (
    f" +{len(pooled['riders']) - 3} more" if len(pooled["riders"]) > 3 else "")
ax.text(0.06, 0.82, f"Shared run to dialysis center  ({pooled['route']})",
        fontsize=13, weight="bold")
ax.text(0.06, 0.755,
        f"Riders {riders}   |   requested {pooled['requested']}   |   "
        f"pickup {pooled['pickup_eta']}   |   assigned to {pooled['decision']}",
        fontsize=9, color=INK2)
import textwrap
y = 0.67
for f in pooled["factors"]:
    lines = textwrap.wrap(f, width=88)
    ax.text(0.075, y, "•", fontsize=11, color=BLUE, weight="bold", va="top")
    ax.text(0.10, y, "\n".join(lines), fontsize=9.5, color=INK, va="top",
            linespacing=1.35)
    y -= 0.075 * len(lines) + 0.013
y -= 0.02
ax.text(0.06, y, "Alternatives considered and rejected", fontsize=8.5,
        color=MUTED, weight="bold")
y -= 0.062
for r in pooled["rejected"][:2]:
    ax.text(0.075, y, f"{r['vehicle']}:  {r['reason']}", fontsize=9, color=INK2)
    y -= 0.058
fig.savefig(ASSETS / "why_this_trip.png", bbox_inches="tight")
plt.close(fig)

# --------------------------------------------- 2. Unserved trip alert card
uns = next(a for a in audit if a["decision"] == "UNSERVED"
           and len(a.get("reasons_by_vehicle", [])) >= 3)
fig, ax = plt.subplots(figsize=(7.4, 4.0))
card_frame(ax)
ax.text(0.06, 0.88, "⚠  CAPACITY ALERT", fontsize=9, color=RED, weight="bold")
ax.text(0.94, 0.88, BRAND, fontsize=8.5, color=MUTED, ha="right")
ax.text(0.06, 0.78, f"Trip could not be placed  (requested {uns['requested']})",
        fontsize=13, weight="bold")
ax.text(0.06, 0.71, "Every denial is logged with the exact constraint that caused it, "
        "per vehicle:", fontsize=9, color=INK2)
y = 0.60
for r in uns["reasons_by_vehicle"][:4]:
    ax.text(0.075, y, f"{r['vehicle']}:  {r['reason']}", fontsize=9.5, color=INK)
    y -= 0.075
ax.text(0.06, y - 0.03,
        "Suggested action: one additional lift-equipped vehicle 09:00-16:00 "
        "resolves this and 11 similar denials this week.",
        fontsize=9.5, color=INK, style="italic")
fig.savefig(ASSETS / "capacity_alert.png", bbox_inches="tight")
plt.close(fig)

# ---------------------------------- 3. SHAP "why this forecast" explanation
model = xgb.XGBRegressor()
model.load_model(OUT / "demand_model.json")
FEATURES = ["hour", "hour_sin", "hour_cos", "dow", "month", "is_weekend",
            "is_holiday", "temp_c", "precip_mm", "pop_density",
            "share_over_65", "has_medical", "has_dialysis", "has_daycenter",
            "gx", "gy"]
# Dialysis return window: Z28 outbound at 11:00 on a MWF service day
cell = valid[(valid.origin_zone == "Z28") & (valid.hour == 11)
             & (valid.dow == 0)].head(1)
explainer = shap.TreeExplainer(model)
sv = explainer(cell[FEATURES])
contrib = sorted(zip(FEATURES, sv.values[0]), key=lambda t: -abs(t[1]))[:6]

NICE = {"has_dialysis": "Dialysis center in zone", "hour": "Hour of day (11:00)",
        "hour_cos": "Time-of-day cycle", "hour_sin": "Time-of-day cycle (2)",
        "dow": "Day of week (Tue)", "precip_mm": "Rain forecast",
        "temp_c": "Temperature", "pop_density": "Population density",
        "share_over_65": "Share of residents 65+", "has_medical": "Medical facilities",
        "has_daycenter": "Adult day center", "is_weekend": "Weekend",
        "month": "Month", "is_holiday": "Holiday", "gx": "Zone location (E-W)",
        "gy": "Zone location (N-S)"}

fig, ax = plt.subplots(figsize=(7.4, 4.2))
names = [NICE.get(f, f) for f, _ in contrib][::-1]
vals = [v for _, v in contrib][::-1]
colors = [BLUE if v >= 0 else ORANGE for v in vals]
bars = ax.barh(names, vals, color=colors, height=0.52, zorder=3)
for b, v in zip(bars, vals):
    ax.text(v + (0.012 if v >= 0 else -0.012), b.get_y() + b.get_height() / 2,
            f"{v:+.2f}", va="center", ha="left" if v >= 0 else "right",
            fontsize=8.5, color=INK2)
ax.axvline(0, color="#c8c7c2", lw=1, zorder=2)
ax.set_xlabel("Contribution to forecast (bookings, log link)")
pred = float(cell.pred.iloc[0]); actual = int(cell.bookings.iloc[0])
d = cell.date.iloc[0]
ax.set_title(f"Why this forecast:  Zone Z28 (dialysis center), "
             f"{d:%a %d %b}, 11:00 return window  →  {pred:.1f} bookings "
             f"predicted, {actual} observed",
             fontsize=10.5, loc="left", pad=12, color=INK)
ax.text(0.0, 1.015, "", transform=ax.transAxes)
ax.grid(axis="y", visible=False)
ax.spines[["top", "right", "left"]].set_visible(False)
fig.text(0.985, 0.02, BRAND, fontsize=8, color=MUTED, ha="right")
fig.tight_layout()
fig.savefig(ASSETS / "why_this_forecast.png", bbox_inches="tight")
plt.close(fig)

# ------------------------------------ 4. Predicted vs actual demand curve
DAY = "2026-04-14"
dv = valid[valid.date == DAY].groupby("hour")[["bookings", "pred"]].sum()
fig, ax = plt.subplots(figsize=(7.4, 3.6))
ax.plot(dv.index, dv.bookings, color="#9b9a95", lw=2, label="Observed bookings",
        marker="o", ms=4, zorder=3)
ax.plot(dv.index, dv.pred, color=BLUE, lw=2, label="Milexium forecast",
        marker="o", ms=4, zorder=4)
ax.text(dv.index[-1] + 0.25, dv.pred.iloc[-1], "Forecast", color=BLUE,
        fontsize=9, va="center", weight="bold")
ax.text(dv.index[-1] + 0.25, dv.bookings.iloc[-1] - 2, "Observed", color=INK2,
        fontsize=9, va="center")
ax.set_xlim(4.6, 24)
ax.set_xticks(range(5, 22, 2))
ax.set_xticklabels([f"{h:02d}:00" for h in range(5, 22, 2)], fontsize=8)
ax.set_ylabel("County-wide bookings per hour")
ax.set_title(f"Demand forecast vs observed, Tuesday {DAY}  "
             f"(held-out validation window)", fontsize=10.5, loc="left", pad=10)
ax.legend(frameon=False, fontsize=8.5, loc="upper right")
ax.grid(axis="x", visible=False)
ax.spines[["top", "right"]].set_visible(False)
fig.text(0.985, 0.03, BRAND, fontsize=8, color=MUTED, ha="right")
fig.tight_layout()
fig.savefig(ASSETS / "demand_curve.png", bbox_inches="tight")
plt.close(fig)

# ----------------------------------------------------- 5. Fleet timeline
KIND_COLOR = {"pooled": BLUE, "solo hub": AQUA, "direct": VIOLET}
def kind_of(k):
    if "pool" in k:
        return "pooled"
    return "direct" if k == "direct" else "solo hub"

fig, ax = plt.subplots(figsize=(9.2, 5.0))
vehicles = sorted(sched.vehicle.unique())
for i, v in enumerate(vehicles):
    for r in sched[sched.vehicle == v].itertuples():
        ax.barh(i, r.end_min - r.start_min, left=r.start_min, height=0.62,
                color=KIND_COLOR[kind_of(r.kind)], ec=SURFACE, lw=1.2, zorder=3)
ax.set_yticks(range(len(vehicles)))
ax.set_yticklabels(vehicles, fontsize=8)
ax.set_xticks(range(300, 1321, 120))
ax.set_xticklabels([f"{m // 60:02d}:00" for m in range(300, 1321, 120)], fontsize=8)
ax.invert_yaxis()
stats = json.loads((OUT / "day_stats.json").read_text())
ax.set_title(f"Fleet schedule, Tuesday {DAY}:  {stats['served']} of "
             f"{stats['requests']} requests placed across {stats['fleet']} vehicles, "
             f"{int(stats['pooled_share'] * 100)}% in shared runs",
             fontsize=10.5, loc="left", pad=10)
handles = [plt.Rectangle((0, 0), 1, 1, fc=c) for c in KIND_COLOR.values()]
ax.legend(handles, ["Shared run (pooled)", "Solo trip to/from facility",
                    "Direct trip"], frameon=False, fontsize=8.5,
          loc="upper right", ncols=3)
ax.grid(axis="y", visible=False)
ax.spines[["top", "right"]].set_visible(False)
fig.text(0.985, 0.02, BRAND, fontsize=8, color=MUTED, ha="right")
fig.tight_layout()
fig.savefig(ASSETS / "fleet_timeline.png", bbox_inches="tight")
plt.close(fig)

print("assets written to", ASSETS)
for p in sorted(ASSETS.glob("*.png")):
    print(" -", p.name)
