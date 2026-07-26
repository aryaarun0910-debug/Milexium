# platform/ops/

Operational readiness: observability, recovery, and security procedures for
whatever is actually deployed. Empty of procedures until something in
`app/` reaches the "Advisory operations" or "Controlled execution"
deployment tier defined in `blueprint/10-security-privacy-and-ai-governance.md`
— writing incident-response runbooks for infrastructure that doesn't run yet
would be fiction, not readiness.

- **`observability/`** — OpenTelemetry conventions, redaction/allowlist rules.
- **`recovery/`** — backup, restore, and corruption-recovery drills and results.
- **`security/`** — vulnerability intake, secret-scanning config, incident process.

**Owner:** whoever owns the deployed capability; no capability is "Production"
per the status vocabulary without a named owner here.
