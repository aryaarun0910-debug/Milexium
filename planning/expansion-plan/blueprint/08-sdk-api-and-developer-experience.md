# SDK, API, and developer experience

## Adoption objective

A competent Python developer should be able to validate a local dataset, run a
reference forecast and schedule, inspect structured evidence, and reproduce the
result in under ten minutes without creating a cloud account.

That is the first credible infrastructure proof. A broad API catalog with no
successful external user is not.

## Public surfaces

### Python SDK

```python
from milexium import Workspace

mx = Workspace.local("./milexium-workspace")
report = mx.connect.csv("./sample-agency", mapping="paratransit-v0")
report.require_valid()

forecast = mx.forecast.demand(
    service_date="2026-07-24",
    horizon="24h",
    as_of="2026-07-23T12:00:00Z",
)

plan = mx.decide.build_manifest(
    service_date="2026-07-24",
    policy="reference-agency@1",
    forecast=forecast,
)

print(plan.evidence())
mx.replay.compare(plan, baseline="reference")
```

### CLI

```text
mx init
mx validate sample/
mx import sample/ --mapping paratransit-v0
mx forecast demand --horizon 24h --as-of ...
mx decide manifest --policy reference-agency@1
mx evidence verify dec_...
mx replay run --baseline reference
```

### HTTP API

Use job resources for expensive work:

```text
POST /v1/imports
POST /v1/forecasts
POST /v1/decision-jobs
GET  /v1/decision-jobs/{id}
POST /v1/overrides
POST /v1/replay-jobs
GET  /v1/decisions/{id}/evidence
POST /v1/evidence/{id}/verify
GET  /v1/registry/models
GET  /v1/registry/solvers
GET  /health
GET  /ready
GET  /version
```

OpenAPI provides a language-agnostic description of HTTP services that tools and
people can inspect without source access. Publish the contract and generate SDK
types/tests from it. [OpenAPI specification](https://spec.openapis.org/oas/latest.html)

## API invariants

Every mutation:

- accepts an idempotency key;
- returns a stable resource ID;
- records actor, tenant, correlation, and trace;
- validates schema and content type;
- has an explicit deadline or creates a job;
- never silently changes policy/model/solver aliases during execution;
- records the resolved versions;
- exposes retry and cancellation semantics.

Every response includes:

- request and schema version;
- state or artifact references;
- warnings and data-quality status;
- error or abstention semantics;
- provenance/trace references;
- timestamps and timezone behavior.

## Error model

Errors are structured:

```json
{
  "error": {
    "code": "STATE_INFORMATION_AFTER_CUTOFF",
    "message": "The snapshot contains records unavailable at replay cut-off.",
    "retryable": false,
    "details": [{"path": "imports[2]", "recorded_at": "..."}],
    "trace_id": "trc_...",
    "documentation_url": "https://docs.milexium.com/errors/..."
  }
}
```

Separate validation, authorization, conflict, deadline, solver, plugin, data
quality, and internal failures. Do not return an infeasible schedule as an HTTP
500 or disguise a failed job as an empty plan.

## Compatibility

Version independently but publish a tested matrix:

- Milexium SDK;
- API;
- canonical schema;
- adapter;
- task specification;
- policy package;
- model and solver plugin interface;
- evidence format.

Rules:

- breaking API/schema changes require a major version after 1.0;
- additive fields are optional to old readers;
- enum expansion behavior is documented;
- unknown extensions are preserved where possible;
- deprecations include telemetry, migration tools, and removal date;
- exact replay pins versions rather than floating aliases.

## Plugin packages

Names:

```text
milexium-core
milexium-schema
milexium-adapter-csv
milexium-adapter-gtfs
milexium-model-demand-baseline
milexium-solver-ortools
milexium-policy-paratransit-us
```

Plugins publish a signed manifest, supported version range, license, origin,
security contact, fixtures, conformance results, and maturity. Untrusted plugins
should run out of process or in a constrained execution environment before
enterprise use.

## Ten-minute quickstart design

The quickstart must:

1. install from one pinned package command;
2. use a small, clearly fictional dataset;
3. run without proprietary maps, credentials, or network calls;
4. finish predictably on a normal laptop;
5. print the baseline and selected result;
6. show one rejected alternative and exact constraint;
7. verify an evidence bundle;
8. state clearly which results are synthetic.

Automate this path in CI on Windows, Linux, and macOS before claiming portability.

## Documentation

Required:

- concept guide and architecture;
- task specifications;
- canonical schema reference;
- adapter authoring guide;
- model and solver plugin guides;
- API/SDK reference;
- policy and reason-code catalog;
- end-to-end tutorials;
- deployment/security guides;
- version and migration notes;
- troubleshooting/error catalog;
- claims and limitations page.

Examples must run as tests. A documentation snippet that silently rots is a product
failure.

## Neutral deployment modes

- local library and CLI;
- self-hosted container;
- Milexium-managed cloud;
- customer virtual private cloud;
- offline replay/evidence appliance where required.

Do not promise all modes initially. The same contracts and conformance suite should
make them possible while commercial demand decides which receive support.

