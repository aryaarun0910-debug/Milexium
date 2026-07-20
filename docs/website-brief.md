# Website Brief: TransitPulse first pass

First pass, due end of Day 1 (of a 3-day sprint). This doc is everything Chris needs to start without waiting on anyone. Arya handles the model, data pipeline, and real API in parallel; Chris builds the frontend against the mock data contract in section 6, and we swap in the real API when it lands.

## 1. What we are building and why

TransitPulse repositions the EWB bus routing project as a US-facing product: demand-predictive route analysis for small transit operators (campus shuttles, airport landside shuttles, hospital district circulators, small city agencies). The incumbents (Optibus, Via/Remix, Swiftly) sell six-figure enterprise contracts to big agencies. Our wedge is self-serve and bottom-up: pick your agency or hub in the browser, see an hourly predicted demand heatmap over your actual stops, get a "mismatch score" showing where scheduled capacity disagrees with predicted demand, and see one optimized counterproposal with an annual dollar figure attached.

The website IS the product demo. It is not a brochure with a "book a demo" button. The interactive map is the landing page.

## 2. First-pass scope (what "done" means for pass one)

A deployed site (Vercel) with:

1. Landing page: hero copy, the interactive map demo, a "how it works" strip, a metrics strip, an email capture form.
2. Methodology page: static content, copy provided in section 5.
3. About page: short, three of us, EWB story.
4. Demo runs entirely on canned JSON files (section 6). No live backend needed for pass one.
5. Mobile: map demo can degrade to a static screenshot plus the mismatch score card on small screens. Do not burn time making MapLibre nice on phones.

Explicitly OUT of scope for pass one: auth, payments, live GTFS search across all agencies (the agency picker is a dropdown of 3 canned agencies), the optimizer running live, any CMS.

## 3. Stack

Build in `web/` in this repo. Reuse the dashboard stack from ewb_bus_routing_project, it already does 80% of the demo:

- React 19 + TypeScript + Vite (lift the existing dashboard app as the starting point)
- MapLibre GL for the map (existing stop/route rendering code carries over)
- Framer Motion for the hero and transitions (already a dependency)
- Tailwind if you want it for the marketing sections, your call
- Email capture: Tally or Formspree embed, no backend
- Deploy: Vercel, connect this repo, root directory `web/`

What changes from the EWB dashboard:
- Stops/routes come from per-agency JSON (real US GTFS shapes, Arya provides) instead of the 15 Ladywood stops
- The ConditionsPanel concept survives but simplified: hour slider, weekday/weekend toggle, weather toggle
- New component: MismatchScore card (section 4)
- Strip all Ladywood/EWB/Birmingham references from the product UI

## 4. Landing page structure, top to bottom

1. **Hero.** Headline, subhead, one CTA button that scrolls to the demo. Dark background, map texture or a blurred screenshot behind it.
2. **Demo section.** Left (or top): agency dropdown (3 canned options), hour slider (5am to 11pm), day-type toggle, weather toggle. Center: MapLibre map, stops sized/colored by predicted demand for the selected hour, route polylines drawn. Right (or below): the MismatchScore card.
3. **MismatchScore card.** The productized headline number. Big number 0 to 100 (higher is worse), one line of interpretation ("Your 7am service is oversupplied, your 3pm service is undersupplied"), a small bar chart of demand vs scheduled capacity by hour, and a gated CTA: "Get the full report" opens the email form.
4. **How it works strip.** Three steps: (1) We read your public GTFS feed, (2) Our model predicts hourly demand per stop from open data (weather, calendars, census, land use), (3) We propose a zero-cost reallocation of your existing vehicles.
5. **Credibility/metrics strip.** Four stats, static: "R2 0.94 demand model (temporal validation)", "1.16% mean routing optimality gap", "<2s solve time", "~$18k/yr projected savings on a 3-vehicle pilot". Link to Methodology.
6. **Email capture.** "See your agency's mismatch score. We'll run your feed and send the report." Fields: email, agency/organization name. That list is the entire point of the site.
7. **Footer.** About link, Methodology link, contact email.

## 5. Copy (use as-is, edit freely for fit)

**Headline options (pick one):**
- "Your bus schedule is wrong. Here's exactly where."
- "See where your transit service disagrees with demand."

**Subhead:** "TransitPulse predicts hourly rider demand for any US transit feed from open data alone, no hardware, no integration, and shows you the zero-cost route changes that serve more riders with the buses you already run."

**CTA button:** "See a live demo" (scrolls to demo section)

**Methodology page (outline, expand from the EWB README):**
- The problem with static schedules post-2020 (hybrid work broke the fixed peak)
- Demand model: XGBoost on weather, school/university calendars, day type, census and land-use features; trained and validated on real US automatic passenger counter data (Arya supplies the exact datasets and validation numbers by Day 2, leave placeholders)
- Routing: capacitated VRP, greedy construction + 2-opt, mean 1.16% gap vs exact optimum on small instances, sub-2s solves
- Honest limitations section (this builds trust with transit planners, they are a skeptical audience): transfer to agencies without passenger counters, small-instance optimality only, predictions are estimates not measurements

**About page:** Team LatencyZero, met at Loughborough, competed in the EWB UK Engineering for People Design Challenge 2026 Grand Finals with a demand-predictive routing system for Ladywood, Birmingham, including a physical FPGA-driven LED map of the network. Now applying it to US transport hubs as TransitPulse. Photos of the LED map here, it is memorable.

## 6. Data contract (build against these, real files replace them later)

Put canned files in `web/public/data/`. Arya delivers real versions of these for 3 agencies by end of Day 1; until then generate plausible mock data with the same shapes.

`data/agencies.json`
```json
[
  { "id": "trimet-portland", "name": "TriMet (Portland, OR)", "center": [-122.676, 45.523], "zoom": 11 },
  { "id": "psu-shuttle", "name": "Campus shuttle example", "center": [-122.685, 45.511], "zoom": 13 },
  { "id": "airport-landside", "name": "Airport landside shuttle example", "center": [-122.597, 45.588], "zoom": 12 }
]
```

`data/{agencyId}/stops.json`
```json
[
  { "stop_id": "9302", "name": "SW 5th & Oak", "lat": 45.5202, "lon": -122.6742 }
]
```

`data/{agencyId}/routes.json`
```json
[
  { "route_id": "20", "name": "Route 20", "color": "#2b6cb0",
    "shape": [[-122.6742, 45.5202], [-122.6731, 45.5210]] }
]
```

`data/{agencyId}/demand.json` (predicted riders per stop per hour, keyed by scenario)
```json
{
  "weekday_clear": { "9302": { "5": 4, "6": 11, "7": 28, "8": 35 } },
  "weekday_rain":  { "9302": { "5": 3, "6": 9,  "7": 31, "8": 38 } },
  "weekend_clear": { "9302": { "5": 1, "6": 2,  "7": 6,  "8": 9 } },
  "weekend_rain":  { "9302": { "5": 1, "6": 2,  "7": 5,  "8": 8 } }
}
```

`data/{agencyId}/mismatch.json`
```json
{
  "score": 62,
  "headline": "Oversupplied 6-9am, undersupplied 2-5pm",
  "by_hour": [ { "hour": 5, "predicted_demand": 40, "scheduled_capacity": 120 } ],
  "annual_cost_of_mismatch_usd": 18400
}
```

Later (Day 2-3) these become API endpoints with identical shapes: `GET /api/agencies`, `GET /api/agencies/{id}/stops`, etc. Fetch from `/data/` behind a single `getData(path)` helper so the swap is a one-line base-URL change.

## 7. Design direction

- Dark UI for the map/demo (transit control-room feel), light for the marketing sections, or dark throughout if that is faster. The EWB dashboard's existing look is a fine starting point.
- Demand coloring on the map: single-hue ramp (light to saturated), circle radius also scales with demand. Do not use red/green as the only signal.
- Mismatch score color: neutral/blue at low scores, amber then red as it rises.
- One font, system stack or Inter. No stock photos of buses.

## 8. Assets and access Chris needs from Arya

- The 3 agencies' real JSON files (Day 1 evening)
- Final validation numbers for the Methodology page (Day 2)
- LED map photos for the About page
- Domain name + Vercel project access

## 9. Chris's day-by-day

- Day 1: `web/` scaffold, lift dashboard code, landing page skeleton, map rendering canned stops/routes with the hour slider working against mock data, deploy to Vercel (deploy on Day 1 even if rough, everything after is iteration on a live URL).
- Day 2: MismatchScore card, demand heatmap polish, scenario toggles, methodology and about pages, email capture wired, swap in real data files as they arrive.
- Day 3: real API swap if ready (otherwise ship on static files, that is fine), copy pass, mobile degradation, favicon/OG image, final deploy on the real domain.
