"""Generate a realistic synthetic paratransit booking dataset.

Fictional mid-size US county agency ("Harland County Mobility"), 12 months of
door-to-door ADA paratransit bookings. Anchored to public NTD demand-response
norms: ~1.5-2.5 passenger trips per revenue vehicle hour, ~50% subscription
(standing-order) trips, medical/dialysis as the dominant purpose, midday
demand peaks rather than commuter peaks, 10-20% cancellation/no-show.

No real rider data anywhere. Output: pipeline/output/trips.csv, zones.csv, weather.csv
"""

import numpy as np
import pandas as pd
from pathlib import Path

rng = np.random.default_rng(42)
OUT = Path(__file__).parent / "output"
OUT.mkdir(exist_ok=True)

# ---------------------------------------------------------------- service area
# 8x8 zone grid, 3km cells (24x24 km county). Town center near (3.5, 3.5).
GRID = 8
zones = []
for gy in range(GRID):
    for gx in range(GRID):
        d_center = np.hypot(gx - 3.5, gy - 3.5)
        pop_density = float(np.exp(-0.35 * d_center) * 2400 + rng.uniform(20, 120))
        share_over_65 = float(np.clip(rng.normal(0.19 + 0.015 * d_center, 0.04), 0.08, 0.42))
        zones.append({
            "zone_id": f"Z{gy * GRID + gx:02d}", "gx": gx, "gy": gy,
            "pop_density": round(pop_density, 1),
            "share_over_65": round(share_over_65, 3),
            "has_medical": 0, "has_dialysis": 0, "has_daycenter": 0,
        })
zones = pd.DataFrame(zones)
# Medical cluster near center, dialysis center, two adult day centers
zones.loc[zones.zone_id.isin(["Z27", "Z28", "Z36"]), "has_medical"] = 1
zones.loc[zones.zone_id == "Z28", "has_dialysis"] = 1
zones.loc[zones.zone_id.isin(["Z19", "Z44"]), "has_daycenter"] = 1
zones.to_csv(OUT / "zones.csv", index=False)

MEDICAL_ZONES = zones[zones.has_medical == 1].zone_id.to_list()
DAYCENTER_ZONES = zones[zones.has_daycenter == 1].zone_id.to_list()
CENTER_ZONES = zones.nlargest(6, "pop_density").zone_id.to_list()

# ---------------------------------------------------------------- riders
N_RIDERS = 1800
home_w = (zones.pop_density * (0.5 + zones.share_over_65)).to_numpy()
home_w = home_w / home_w.sum()
riders = pd.DataFrame({
    "rider_id": [f"R{i:04d}" for i in range(N_RIDERS)],
    "home_zone": rng.choice(zones.zone_id, N_RIDERS, p=home_w),
    "wheelchair": rng.random(N_RIDERS) < 0.20,
})
# Subscription cohorts: dialysis MWF or TTS, day-program weekdays
riders["subscription"] = "none"
dial_idx = rng.choice(N_RIDERS, 80, replace=False)
riders.loc[dial_idx[:45], "subscription"] = "dialysis_mwf"
riders.loc[dial_idx[45:], "subscription"] = "dialysis_tts"
rest = riders.index[riders.subscription == "none"]
riders.loc[rng.choice(rest, 55, replace=False), "subscription"] = "dayprogram"

# ---------------------------------------------------------------- weather
dates = pd.date_range("2025-07-01", "2026-06-30", freq="D")
doy = dates.dayofyear.to_numpy()
temp = 12 + 12 * np.sin((doy - 105) / 365 * 2 * np.pi) + rng.normal(0, 3.5, len(dates))
precip_p = 0.22 + 0.10 * np.sin((doy - 20) / 365 * 2 * np.pi)
precip = np.where(rng.random(len(dates)) < precip_p, rng.gamma(2, 3, len(dates)), 0.0)
weather = pd.DataFrame({"date": dates, "temp_c": temp.round(1), "precip_mm": precip.round(1)})
weather.to_csv(OUT / "weather.csv", index=False)

HOLIDAYS = pd.to_datetime([
    "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25", "2026-01-01",
    "2026-01-19", "2026-05-25", "2026-06-19",
])

# ---------------------------------------------------------------- bookings
# Hourly demand profile: medical peaks 8-10 and 13-15, returns 11-12 and 15-17.
PURPOSES = ["medical", "dialysis", "dayprogram", "work", "shopping", "other"]
HOUR_PROFILE = {
    "medical":   {8: .18, 9: .22, 10: .14, 11: .08, 13: .16, 14: .12, 15: .10},
    "dialysis":  {5: .30, 6: .35, 11: .15, 12: .20},
    "dayprogram": {8: .5, 9: .5},
    "work":      {6: .25, 7: .45, 8: .30},
    "shopping":  {10: .35, 11: .30, 13: .35},
    "other":     {9: .2, 10: .2, 12: .2, 14: .2, 16: .2},
}

def pick_hour(purpose):
    prof = HOUR_PROFILE[purpose]
    return int(rng.choice(list(prof), p=np.array(list(prof.values())) / sum(prof.values())))

def pick_dest(purpose, home):
    if purpose == "dialysis":
        return "Z28"
    if purpose == "medical":
        return rng.choice(MEDICAL_ZONES)
    if purpose == "dayprogram":
        return rng.choice(DAYCENTER_ZONES)
    if purpose in ("work", "shopping"):
        return rng.choice(CENTER_ZONES)
    return rng.choice(zones.zone_id)

rows = []
sub_mwf = riders[riders.subscription == "dialysis_mwf"]
sub_tts = riders[riders.subscription == "dialysis_tts"]
sub_day = riders[riders.subscription == "dayprogram"]
casual = riders[riders.subscription == "none"]

for i, d in enumerate(dates):
    dow, is_holiday = d.dayofweek, d in HOLIDAYS
    wx = weather.iloc[i]
    if is_holiday:
        base = 30
    elif dow < 5:
        base = 130
    else:
        base = 55
    # Subscriptions (standing orders) run on their fixed days
    subs = []
    if not is_holiday:
        if dow in (0, 2, 4):
            subs.append((sub_mwf, "dialysis"))
        if dow in (1, 3, 5):
            subs.append((sub_tts, "dialysis"))
        if dow < 5:
            subs.append((sub_day, "dayprogram"))
    for cohort, purpose in subs:
        for _, r in cohort.iterrows():
            h = pick_hour(purpose)
            dest = pick_dest(purpose, r.home_zone)
            for (o, dst, hh) in [(r.home_zone, dest, h), (dest, r.home_zone, min(h + 5, 21))]:
                rows.append((d, hh, r.rider_id, o, dst, purpose, r.wheelchair, True))
    # Casual (demand-response) bookings, outbound + return
    wx_mult = 1.0
    if wx.precip_mm > 8:
        wx_mult *= 0.78
    elif wx.precip_mm > 2:
        wx_mult *= 0.90
    if wx.temp_c < -2 or wx.temp_c > 32:
        wx_mult *= 0.88
    n_casual = max(0, int(rng.poisson(base * wx_mult)))
    picked = casual.sample(n=min(n_casual // 2, len(casual)), random_state=int(i))
    for _, r in picked.iterrows():
        purpose = rng.choice(PURPOSES, p=[.38, 0, 0, .14, .22, .26])
        h = pick_hour(purpose)
        dest = pick_dest(purpose, r.home_zone)
        ret_h = min(h + int(rng.integers(2, 5)), 21)
        rows.append((d, h, r.rider_id, r.home_zone, dest, purpose, r.wheelchair, False))
        rows.append((d, ret_h, r.rider_id, dest, r.home_zone, purpose, r.wheelchair, False))

trips = pd.DataFrame(rows, columns=[
    "date", "hour", "rider_id", "origin_zone", "dest_zone",
    "purpose", "wheelchair", "subscription"])
# Minute within hour, requested pickup time
trips["req_minute"] = rng.integers(0, 60, len(trips))
# Cancellations and no-shows: higher in heavy rain
precip_map = weather.set_index("date").precip_mm
p_cancel = 0.11 + 0.05 * (precip_map.reindex(trips.date).to_numpy() > 8)
u = rng.random(len(trips))
trips["status"] = np.where(u < p_cancel, "cancelled", np.where(u < p_cancel + 0.045, "no_show", "completed"))
trips.to_csv(OUT / "trips.csv", index=False)

n_days = len(dates)
print(f"zones: {len(zones)}, riders: {N_RIDERS}, days: {n_days}")
print(f"bookings: {len(trips):,} ({len(trips)/n_days:.0f}/day avg)")
print(trips.status.value_counts(normalize=True).round(3).to_dict())
print(trips.purpose.value_counts(normalize=True).round(3).to_dict())
