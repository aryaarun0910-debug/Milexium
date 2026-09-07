# Risks, assumptions, and falsification

## Why this document exists

The expansion thesis is ambitious enough that weak assumptions can survive
inside architecture diagrams and agent-generated implementations. Each major
belief needs a test and an architectural response.

## Assumption register

| Assumption | Fastest credible test | Positive signal | Falsifying signal | Response |
|---|---|---|---|---|
| Agencies struggle to reconstruct decision evidence | Walk through recent disputed trips with records/screens | Multiple systems/manual effort and named consequence | Existing system produces complete evidence quickly | Narrow or abandon evidence wedge |
| Vendor-neutral import is feasible | Map two authorized heterogeneous exports | Core semantics survive with bounded extensions | Meaning is mostly vendor-private or unavailable | Sell source-specific analytics, not universal schema |
| Replay is valuable before live control | Deliver read-only historical assessment | Buyer commits time/data/budget to next run | Interesting demo, no workflow or budget | Focus on another land product |
| Forecasts improve planning | Pre-register shadow decision and metric | Forecast changes capacity action and outcome | High accuracy produces no operational action | Reframe task or stop model work |
| Constraint evidence is comprehensible | Dispatcher/compliance usability test | Faster/correcter reconstruction | Codes confuse or omit actual judgment | Redesign evidence vocabulary/workflow |
| Developers want a transport SDK | External ten-minute test and follow-up use | Repeat runs, issue/plugin/benchmark submission | Install only, no retained use | Stop open-platform investment |
| Open core drives commercial adoption | Track local-to-private conversion | Private data/scale/support demand | Users fork toy or no adoption | Change boundary or distribution |
| Better models strengthen Milexium | Integrate external challenger | Same task/evidence path absorbs it | Every model needs bespoke pipeline | Core contracts are too weak |
| Policy can be executable | Encode operator rules with edge fixtures | Operator approves semantics and tests | Critical rules depend on undocumented judgment | Keep human workflow explicit |
| Decision/outcome data compounds | Compare later deployments and model choices | Reuse reduces integration/evaluation cost | Data cannot be pooled or semantics never align | Moat is workflow/trust, not data |
| Another adapter reuses the core | Implement only after partner exists | Most core contracts reused unchanged | Requires new entities/runtime/product | Separate product or reject segment |

## Strategic risks

### Infrastructure before demand

Risk: building registries, plugin systems, and cloud control planes without users.

Control: every platform phase requires an external workflow or conformance use.
Prefer a local vertical slice over horizontal empty abstractions.

### Incumbent feature response

Risk: a dispatch vendor adds better evidence and replay inside its installed suite.

Control: prove cross-vendor neutrality, benchmark independence, integration speed,
and model/solver portability. If customers prefer incumbent-native evidence,
partner or narrow.

### No access to operational data

Risk: public aggregate data cannot validate trip-level decisions.

Control: keep claims narrow; use academic optimization benchmarks and fictional
policy fixtures; make a data-readiness assessment the first product. Do not fill
missing real evidence with synthetic volume.

### Standard fragmentation

Risk: canonical state becomes a private standard that duplicates TDS, GTFS Flex,
TODS, TIDES, NeTEx, or vendor schemas.

Control: publish mappings and departures; contribute validators/adapters; keep
source semantics; require two-source evidence before promoting common fields.

### Model-agnostic lowest-common denominator

Risk: generic contracts exclude advanced model/solver capabilities or become a
bag of extensions.

Control: small stable core, task-specific capabilities, namespaced extensions,
compatibility negotiation, and reference conformance cases.

### Optimization explanation limits

Risk: "rejected alternatives" implies exhaustive search when heuristics explored
only a fraction.

Control: record comparison-set provenance, search status, bounds/gaps, and "not
evaluated." Separate infeasibility proof from failure to find a solution.

### Counterfactual overclaim

Risk: replay metrics are interpreted as causal savings.

Control: label observed/derived/simulated fields, holdout information, run
sensitivity, and require shadow/live evaluation before savings claims.

### Safety and automation creep

Risk: advisory output quietly becomes automatic action.

Control: deployment tiers, explicit authorization, separate credentials/endpoints,
human approval, safe degradation, and change audit.

### Privacy and re-identification

Risk: precise trip time/location and operational needs re-identify riders even
without names.

Control: minimize fields; separate identity; use controlled environments; follow
contract/legal determinations; never publish row-level "anonymized" trip data
without proper analysis.

### Open-source commoditization

Risk: a better-funded company hosts the open core.

Control: commercial value in connectors, secure operation, policy/evidence
workflows, outcome history, support, and trust. If those do not materialize, the
business is not protected by license cleverness.

### Agent-swarm divergence

Risk: hundreds of locally plausible changes produce incompatible semantics,
duplicated subsystems, weak integration, or tests written to implementation
mistakes.

Control: normative contracts, disjoint path ownership, generated clients,
independent verifier swarms, hidden tests, merge trains, ADRs, and evidence
manifests.

## Technical failure modes

- future data leaks into replay;
- timezone/DST errors change windows;
- source identity collisions;
- RLS bypass or cross-tenant object path;
- stale model/policy alias resolution;
- plugin side effects or exfiltration;
- solver timeout returned as valid optimal plan;
- capacity violation between stops;
- event-chain integrity without source completeness;
- metrics change definitions across periods;
- redaction misses free text or precise coordinates;
- nondeterministic exact replay;
- schema extension becomes required implicitly;
- model interval is misrepresented as probability/confidence.

Each becomes an automated test or a documented operational drill.

## Evidence-driven adaptation triggers

Experiments redirect architecture and positioning:

| Evidence | Required adaptation |
|---|---|
| Operators value control more than replay | Elevate advisory optimization and approval workflows while retaining evidence |
| Shared schemas lose important vendor meaning | Expand namespaced semantics, source-preserving projections, and mapping proofs |
| Developers prefer embedded components | Strengthen SDK/runtime packaging and conformance certification |
| Outcomes cannot be reconstructed | Invest in Connect, state capture, and operator workflow instrumentation |
| Integrations remain bespoke | Generate adapters from mapping specifications and learn reusable semantic patterns |
| Contracts restrict pooled learning | Use tenant-local models, federated evaluation, confidential compute, and portable verifiers |
| Recommendations create instability | Add stability objectives, freeze horizons, operator burden models, and safer control policies |
| Incumbents match individual features | Differentiate through the joined canonical-state, verifier, experience, and hardware-cost graph |

## Evidence review loop

Continuously:

- update the assumption table;
- attach interview, benchmark, usage, reliability, and commercial evidence;
- downgrade unsupported beliefs;
- redirect weak implementations and research hypotheses;
- publish negative technical findings where safe;
- confirm current public claims against the evidence registry.

The blueprint is a hypothesis system, not scripture.
