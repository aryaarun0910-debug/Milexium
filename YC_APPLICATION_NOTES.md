# TransitPulse — YC Fall 2026 working notes

Deadline: 28 July 2026. Source project: EWB Ladywood bus routing (Grand Final, top 36 of ~13,000 students).

## Decisions locked in during grill session

1. **Customer**: paratransit (ADA-mandated in the US, statutory duty in the UK). Not fixed-route transit agencies — too slow a sales cycle for this timeline.
2. **Geography**: US-first. Bigger, statutorily-funded market, real procurement budgets, and YC is heavily US-market-biased even for non-US teams.
3. **Wedge**: explainability / audit trail, not "bigger model." Paratransit is compliance-heavy (National Transit Database reporting, ADA rules) and incumbents (Ecolane, TripSpark, RouteMatch/Uber Health) are opaque legacy systems. "Here's exactly why the model routed this trip this way" is a real differentiator against them. Already have the groundwork: `analysis/explainability.py`, `MODEL_CARD.md`, `MODEL_COMPARISON.md` (SHAP-based, benchmarked against ARIMA/deep learning).
4. **FPGA/hardware**: cut from the V1 product. It solved Ladywood's fixed-stop community-visibility problem; paratransit is door-to-door/dispatched, no natural place for a physical display. Keep it in the application narrative only, as evidence the team can ship real embedded systems under a deadline — not as part of what gets pitched to a paratransit customer.
5. **"Bigger transformer" idea**: dropped as a stated plan. Model sophistication isn't the blocker for a paratransit customer; integration, trust, and compliance are.
6. **Team**: two founders (Arya + Chris), both UK, no US visa yet, willing to relocate given the opportunity. Be upfront about this in the application rather than dodging it — YC has an immigration support process for accepted international teams.
7. **Current customer contact**: zero. Highest-leverage use of the next ~2 weeks is cold outreach to US paratransit operators/NEMT brokers, run in parallel with (not after) any further engineering — sequencing "more sophisticated model first" ahead of customer contact was identified as an avoidance pattern, not a real technical blocker.

## Open / still to resolve
- Company name (working title "TransitPulse")
- Actual product cut for the application: written narrative + maybe short demo video, reframing EWB's real results (R²=0.94, 1.16% mean VRP optimality gap, ~£14.7k/yr saving via DfT BUS0404 methodology) in paratransit-relevant terms
- Whether to target NEMT brokers (Modivcare, MTM) as channel partners vs. going direct to small regional paratransit operators
- Legal/IP: EWB competition entry ownership — check EWB's terms before commercializing derived IP
