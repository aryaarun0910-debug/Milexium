/**
 * Public type aliases for the Milexium SDK.
 *
 * Every type here is *derived* from `src/generated/openapi.ts`, which is
 * generated from `talos/contracts/openapi/milexium-api-v0.1.json` by the `generate`
 * npm script. Nothing in this file re-declares a field of a canonical domain
 * entity -- it only gives the generated `components["schemas"][...]` shapes
 * ergonomic names and, for the two request bodies, relaxes the optionality of
 * server-defaulted fields to match the contract's actual `required` set. If the
 * contract changes, re-run `npm run generate` and these aliases follow.
 */
import type { components } from "./generated/openapi.ts";

/** All schema shapes exactly as the OpenAPI contract defines them. */
export type Schemas = components["schemas"];

// --- responses (used verbatim) ---------------------------------------------

export type HealthResponse = Schemas["HealthResponse"];
export type VersionResponse = Schemas["VersionResponse"];
export type RecordedEvent = Schemas["RecordedEvent"];
export type EvidencePacket = Schemas["EvidencePacket"];
export type EvidencePack = Schemas["EvidencePack"];
export type VerifyResponse = Schemas["VerifyResponse"];

// --- request bodies as the contract declares them --------------------------

export type RecordDecisionRequest = Schemas["RecordDecisionRequest"];
export type RecordOverrideRequest = Schemas["RecordOverrideRequest"];

// --- supporting domain shapes (re-exported for consumers) ------------------

export type ReasonCode = Schemas["ReasonCode"];
export type DecisionEvent = Schemas["DecisionEvent"];
export type DecisionEventType = Schemas["DecisionEventType"];
export type DecisionAlternative = Schemas["DecisionAlternative"];
export type KnownInput = Schemas["KnownInput"];
export type Outcome = Schemas["Outcome"];
export type PackManifest = Schemas["PackManifest"];
export type ChainViolation = Schemas["ChainViolation"];
export type StateViolation = Schemas["StateViolation"];
export type VerifyViolation = Schemas["VerifyViolation"];
export type HTTPValidationError = Schemas["HTTPValidationError"];

// --- caller-facing request inputs ------------------------------------------
//
// The generated request types mark server-defaulted fields (actor_id,
// aggregate_type, reason_codes) as required because they carry an OpenAPI
// `default`. The contract's own `required` list is narrower, so these inputs
// keep exactly the contract-required fields mandatory and make the rest
// optional -- derived from the generated type via Pick/Partial, still no
// hand-redeclared field shapes.

/** Body for `recordDecision`: contract requires `aggregate_id` + `payload`. */
export type RecordDecisionInput = Pick<
  RecordDecisionRequest,
  "aggregate_id" | "payload"
> &
  Partial<Omit<RecordDecisionRequest, "aggregate_id" | "payload">>;

/** Body for `recordOverride`: contract requires `payload` + `actor_id`
 * (`aggregate_id` travels in the path, so it is not part of the body). */
export type RecordOverrideInput = Pick<
  RecordOverrideRequest,
  "payload" | "actor_id"
> &
  Partial<Omit<RecordOverrideRequest, "payload" | "actor_id">>;
