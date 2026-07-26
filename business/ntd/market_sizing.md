# US demand-response market, bottom-up from NTD

Source: FTA National Transit Database annual data (datasets ekg5-frzt, wwdp-t4re on data.transportation.gov), modes DR and DT. Raw extracts live in business/ntd/raw/ and are pulled by business/ntd/fetch_ntd.py; this table was rebuilt 2026-07-26 from those extracts, which is not the same date as the pull. All figures below are report year 2024 reporters only; business/ntd/agency_economics.csv also carries agencies whose latest filing is 2022 or 2023.

## Totals (2024 report year)

- Agencies reporting demand-response service: 1,920
- Annual demand-response trips: 139,681,610
- Annual operating expense: $7,063,731,406
- Annual vehicle revenue hours: 72,612,006
- Median cost per trip: $37.97
- Mean cost per trip (expense-weighted): $50.57

## National reference distribution (2024)

The comparison baselines. An operator's position in these distributions is computable from its own filing and checkable by the operator; it asserts nothing about what any change would recover.

| metric | p10 | median | p90 | p90/p10 |
|:--|--:|--:|--:|--:|
| Cost per trip | $16.26 | $37.97 | $81.68 | 5.02x |
| Cost per revenue hour | $38.91 | $76.88 | $148.55 | 3.82x |
| Trips per revenue hour | 1.13 | 2.05 | 3.99 | 3.53x |

Roughly half the variation in cost per trip is productivity and roughly half is input price (50.1% price / 49.9% productivity, finding `dr_cost_per_trip_dispersion_2024` in business/outreach/panel_findings.json). Cost per HOUR is the variable that actually ranks with cost per trip: Spearman +0.738 across 406 operators.

## Deadhead (agencies reporting hours detail)

**These are accounting identities, not an opportunity.** `deadhead_cost` is what an operator's empty vehicle-hours cost at its own reported average cost per hour. How much of it is recoverable is unknown: fixed costs do not fall with utilisation and no operator fixed/variable split exists in this repo. No figure in this section may be presented as a saving, an opportunity, or a benefit of adopting Milexium.

- Agencies with deadhead detail: 406
- Their combined operating expense: $5,461,523,956
- Expense-weighted deadhead share of hours: 17.3%
- Combined annual cost of those empty hours (accounting identity): $943,999,574
- Per-agency deadhead share: median 15.1%, p90 25.5%

**Deadhead share does not identify an expensive agency.** Pearson +0.017, OLS R2 0.0003 on n=405 (research/h5b_structure_vs_cost.json). Spearman +0.024 over 406 operators, against +0.738 for cost per hour, with cost per trip essentially flat across deadhead quartiles ($48.53 lowest to $54.09 highest) -- business/outreach/panel_findings.json, finding `dr_deadhead_predicts_cost_per_trip`, REJECTED by the panel gate on effect size. A high deadhead figure is a description of an operator's hours, not a diagnosis of its costs.

## Segmentation by annual trips (2024)

| size_band   |   agencies |    trips |       opex |   median_cost_per_trip |
|:------------|-----------:|---------:|-----------:|-----------------------:|
| under 10k   |        533 |  2554216 |  119790751 |                  43.07 |
| 10k to 50k  |        827 | 20858516 |  835236043 |                  36.29 |
| 50k to 200k |        439 | 41129502 | 1665262538 |                  35.57 |
| over 200k   |        121 | 75139376 | 4443442074 |                  51.43 |

## How to use these numbers

- **Outreach: position, not valuation.** Every row of agency_economics.csv gives an operator its own trips, cost per trip, cost per revenue hour and trips per revenue hour, and the reference distribution above turns those into a national position the operator cannot see from inside its own data. Do not attach a dollar saving to that position -- the gap to the median is not known to be recoverable, and asserting that it is would be the same causal claim the platform refuses to make everywhere else.
- **YC market size: state the spend, not a capture.** The operating expense total above is the annual spend US demand-response runs on. It is a market size. It is not a saving Milexium has created, and no fraction of it may be quoted as one until an operator's own fixed/variable split says what is recoverable.
- **Status: Demonstrated, never Validated.** These are well-measured descriptions of what agencies FILED. No operator has confirmed any of it against their own books.