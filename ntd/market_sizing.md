# US demand-response market, bottom-up from NTD

Source: FTA National Transit Database annual data (datasets ekg5-frzt, wwdp-t4re on data.transportation.gov), modes DR and DT, pulled 2026-07-20. All figures below are report year 2024 reporters only; ntd/agency_economics.csv also carries agencies whose latest filing is 2022 or 2023.

## Totals (2024 report year)

- Agencies reporting demand-response service: 1,920
- Annual demand-response trips: 139,681,610
- Annual operating expense: $7,063,731,406
- Annual vehicle revenue hours: 72,612,006
- Median cost per trip: $37.97
- Mean cost per trip (expense-weighted): $50.57

## Deadhead (agencies reporting hours detail)

- Agencies with deadhead detail: 406
- Their combined operating expense: $5,461,523,956
- Expense-weighted deadhead share of hours: 17.3%
- Combined annual deadhead cost: $943,999,574
- Value of a 10 percent deadhead reduction across them: $94,399,949 per year

## Segmentation by annual trips (2024)

| size_band   |   agencies |    trips |       opex |   median_cost_per_trip |
|:------------|-----------:|---------:|-----------:|-----------------------:|
| under 10k   |        533 |  2554216 |  119790751 |                  43.07 |
| 10k to 50k  |        827 | 20858516 |  835236043 |                  36.29 |
| 50k to 200k |        439 | 41129502 | 1665262538 |                  35.57 |
| over 200k   |        121 | 75139376 | 4443442074 |                  51.43 |

## How to use these numbers

- Outreach: every row of agency_economics.csv gives a personalized opener: trips, cost per trip, deadhead share, and the dollar value of a 10 percent deadhead cut, all from the agency's own NTD filing.
- YC market size: the operating expense total above is the annual spend Milexium optimizes against; software captures a fraction of the savings it creates, not the whole budget. State both numbers plainly.