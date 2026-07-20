# ntd/ : FTA National Transit Database, demand-response universe

Real, government-reported economics for every US demand-response (paratransit
and NEMT) operator. This is the market we sell into, sized bottom-up, and the
raw material for personalized outreach.

Run order:

```
py -3 ntd/fetch_ntd.py               # pulls DR/DT rows from data.transportation.gov
py -3 ntd/build_economics.py         # per-agency table + market sizing
py -3 ntd/build_outreach_targets.py  # tiered 80-target outreach list with hooks
```

Files:

- raw/metrics_dr.csv, raw/service_dr.csv: filtered NTD pulls, 2022-2024,
  modes DR and DT (datasets ekg5-frzt and wwdp-t4re)
- agency_economics.csv: one row per agency, latest report year: trips, opex,
  cost per trip, revenue hours, deadhead share, dollar value of a 10 percent
  deadhead cut, ADA share
- market_sizing.md: national totals and segmentation, 2024 report year

Headline numbers (2024 report year): 1,920 agencies, 139.7M annual trips,
$7.06B operating expense, median $37.97 per trip, expense-weighted deadhead
17.3 percent of vehicle hours.

Method notes: agencies aggregated across DR and DT modes and all service
types (directly operated plus purchased). Deadhead cost attributes operating
expense to hours uniformly. Only full reporters (413 agencies) file deadhead
detail; reduced reporters get cost-per-trip hooks instead.
