# TransitPulse pipeline (v1, synthetic)

Run in order:

```
py -3 pipeline/generate_trips.py    # synthetic county paratransit bookings, 12 months
py -3 pipeline/train_demand.py     # zone-hour XGBoost demand model, temporal validation
py -3 pipeline/schedule_trips.py   # one service day: pooling + assignment + audit trail
py -3 pipeline/make_demo_assets.py # renders docs/demo-assets/*.png
```

Current numbers (seed 42):

- Demand model: R2 0.839 vs 0.817 seasonal-naive, RMSE 0.434 vs 0.463, strict 90-day temporal holdout
- Scheduler: 229/253 requests placed, 77% in shared runs, 20 vehicles, deadhead 17% of drive time
- Every assignment and every denial in `output/audit_log.json` carries factors and rejected alternatives with reasons

## Honesty notes (say these out loud in any demo)

1. All data is synthetic. The generator is anchored to public NTD demand-response
   norms (trips/revenue-hour, subscription share, purpose mix, cancellation rates),
   but the model's headline R2 partly reflects that synthetic demand is more
   regular than real demand. The naive-baseline comparison is reported for
   exactly this reason. Replacing this with a real agency's trip data is the
   first pilot deliverable.
2. The scheduler is a v1 greedy insertion with hub pooling. No en-route
   interleaving, no re-optimization. Its job here is to demonstrate the audit
   trail, not to claim optimality.
3. The "suggested action" line on the capacity alert card is illustrative copy,
   not yet a computed recommendation.
4. Rider ids are synthetic. No PHI exists anywhere in this repo, and the real
   product must be built HIPAA-aware from day one for NEMT.
