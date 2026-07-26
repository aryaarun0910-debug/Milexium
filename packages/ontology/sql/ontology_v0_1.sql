-- Ontology v1 portable schema (MX-ONT-DECISION-SNAPSHOT-013).
--
-- PORTABLE SUBSET ONLY (ADR-0002): no JSONB, no ENUM types (CHECK ... IN (...)
-- instead), no Postgres-only functions, no PostGIS. This file must run
-- unmodified on SQLite and on PostgreSQL 17. Triggers and row-level security
-- are engine-specific and live in their own files, applied on top:
--   ontology_rls_postgres.sql          -- tenant isolation (Postgres only)
--   ontology_immutability_postgres.sql -- append-only + receipt monotonicity
--   ontology_immutability_sqlite.sql   -- the same two invariants, SQLite dialect
--
-- ============================================================================
-- TIMESTAMPS ARE FIXED-WIDTH ISO-8601 UTC TEXT, ALWAYS. NOT NEGOTIABLE.
-- ============================================================================
-- Every timestamp column here is written by packages/ontology/receipt.iso_receipt
-- (which IS packages/core/feature_store._iso_utc -- one function, imported, not
-- copied). Six fractional digits and a literal +00:00, always.
--
-- The reason is that this schema COMPARES timestamps in SQL. `receipt_time < ?`
-- is the point-in-time boundary, and on PostgreSQL a TEXT comparison runs under
-- the database collation rather than byte order. Under this repository's dev
-- collation (English_United Kingdom.1252), '...T09:14:03.500000+00:00' compares
-- as LESS than '...T09:14:03+00:00' -- the wrong way round -- because
-- punctuation and digits are weighted differently. A bare `datetime.isoformat()`
-- elides the fraction when it is zero and would produce exactly that pair.
-- Fixed width makes every stored value identical in punctuation and position, so
-- the comparison degenerates to a digit-by-digit one that is correct under any
-- collation. The counterexample is pinned in the conformance suite.
--
-- ============================================================================
-- THE RECEIPT LOG IS THE SPINE
-- ============================================================================
-- Every other table in this file carries (receipt_time, receipt_sequence) and
-- every one of those pairs was issued by ontology_receipt_log. The log gives a
-- tenant ONE total order across ALL streams -- facts, relationships, events,
-- snapshots, actions, outcomes -- which is what a point-in-time cut actually
-- needs: a snapshot must be able to be taken BETWEEN any two writes, whatever
-- streams they were in, unambiguously.
--
-- It is also where receipt monotonicity is enforced in the database (see the
-- immutability files): a row whose receipt_time is earlier than the tenant's
-- current maximum is REJECTED. That is the invariant that makes an information
-- set final -- once a snapshot at T has been taken, nothing can afterwards
-- appear before T -- and it is why a snapshot rebuilt tomorrow for the same T is
-- byte-identical to the one built today.
--
-- WHAT THERE IS NO FOREIGN KEY TO, AND WHY. There is no REFERENCES clause to
-- packages/canonical's `tenants` table. The ontology schema is applied
-- standalone (its own PostgreSQL schema, its own SQLite file) so this package
-- can be loaded without the canonical one and neither package's migrations
-- order the other's. Tenant containment is enforced by row-level security and
-- by the store's own tenant_id predicates, which is where it belongs -- a
-- foreign key never was the tenant boundary (PostgreSQL evaluates referential
-- integrity with RLS bypassed by design).

-- ---------------------------------------------------------------------------
-- 1. The receipt ledger: one monotonic, hash-chained order per tenant.
-- ---------------------------------------------------------------------------
CREATE TABLE ontology_receipt_log (
    tenant_id        TEXT    NOT NULL,
    receipt_sequence INTEGER NOT NULL CHECK (receipt_sequence >= 1),
    receipt_time     TEXT    NOT NULL,
    stream           TEXT    NOT NULL CHECK (stream IN
        ('object','relationship','fact','event','identity','snapshot','action','outcome')),
    row_id           TEXT    NOT NULL,
    row_hash         TEXT    NOT NULL,
    prev_hash        TEXT,
    hash             TEXT    NOT NULL,
    -- sequence 1 is the only row that may have no predecessor. Stated as a
    -- CHECK so a chain cannot be silently re-rooted by an insert.
    CHECK ((receipt_sequence = 1 AND prev_hash IS NULL)
        OR (receipt_sequence > 1 AND prev_hash IS NOT NULL)),
    PRIMARY KEY (tenant_id, receipt_sequence)
);

-- ---------------------------------------------------------------------------
-- 2. Objects: identity only. There is deliberately NO attribute column here.
--    See packages/ontology/graph.py -- an attribute on an object would have no
--    receipt time, and a decision replayed at time T would read whatever it
--    says now. Statelessness makes that row unrepresentable.
-- ---------------------------------------------------------------------------
CREATE TABLE ontology_objects (
    object_id        TEXT    NOT NULL PRIMARY KEY,
    tenant_id        TEXT    NOT NULL,
    object_kind      TEXT    NOT NULL CHECK (object_kind IN
        ('operator','service_area','depot','rider','eligibility_profile','request',
         'journey','location','protected_zone','vehicle','accessibility_equipment',
         'capacity_profile','driver','shift','run','block','assignment',
         'schedule_version','policy','contract','service_rule','incident','disruption',
         'maintenance_event','forecast','recommendation','override','outcome')),
    external_ref     TEXT,
    source_system    TEXT,
    receipt_time     TEXT    NOT NULL,
    receipt_sequence INTEGER NOT NULL
);

-- ---------------------------------------------------------------------------
-- 3. Relationships: first-class edges with a time extent and a probability.
--    valid_from/valid_to are VALID time (when the edge holds in the world);
--    receipt_time is TRANSACTION time (when Milexium learned it). Both are
--    needed and they are routinely far apart -- a shift swap agreed at 05:50
--    and keyed in at 09:30 is invisible to a 07:00 decision, correctly.
-- ---------------------------------------------------------------------------
CREATE TABLE ontology_relationships (
    relationship_id           TEXT    NOT NULL PRIMARY KEY,
    tenant_id                 TEXT    NOT NULL,
    relationship_kind         TEXT    NOT NULL,
    subject_kind              TEXT    NOT NULL,
    subject_id                TEXT    NOT NULL,
    object_kind               TEXT    NOT NULL,
    object_id                 TEXT    NOT NULL,
    weight                    DOUBLE PRECISION CHECK (weight IS NULL OR (weight >= 0.0 AND weight <= 1.0)),
    valid_from                TEXT,
    valid_to                  TEXT,
    asserted_by               TEXT    NOT NULL,
    retracts_relationship_id  TEXT,
    receipt_time              TEXT    NOT NULL,
    receipt_sequence          INTEGER NOT NULL,
    CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_to >= valid_from),
    CHECK (subject_id <> object_id)
);

-- ---------------------------------------------------------------------------
-- 4. Facts: the point-in-time layer. This is the table the whole packet is
--    about, and `receipt_time` is the only column the boundary is keyed on.
--
--    A VALUE OR A REASON THERE IS NONE, NEVER BOTH AND NEVER NEITHER. The
--    CHECK below is the database's half of the invariant
--    packages/ontology/provenance.SnapshotFact enforces in Python: an
--    unexplained NULL cannot be stored. "Null" is not one fact but nine, and a
--    model trained on undifferentiated nulls learns the operator's
--    data-collection habits as if they were rider behaviour.
--
--    value_kind + three typed columns rather than one TEXT column, because a
--    number stored as text sorts and aggregates wrongly and every consumer would
--    have to remember to cast.
-- ---------------------------------------------------------------------------
CREATE TABLE ontology_facts (
    fact_id           TEXT    NOT NULL PRIMARY KEY,
    tenant_id         TEXT    NOT NULL,
    subject_kind      TEXT    NOT NULL,
    subject_id        TEXT    NOT NULL,
    attribute         TEXT    NOT NULL,
    fact_class        TEXT    NOT NULL CHECK (fact_class IN
        ('observation','prediction','plan','derivation','declaration')),
    value_kind        TEXT    NOT NULL CHECK (value_kind IN
        ('number','text','bool','absent')),
    -- DOUBLE PRECISION, not REAL, throughout this file. PostgreSQL's REAL is
    -- float4 (~7 significant digits) while SQLite's is 8-byte, so a REAL column
    -- silently loses precision on ONE engine and a value written on SQLite and
    -- read on PostgreSQL would not compare equal. `DOUBLE PRECISION` is float8
    -- on PostgreSQL and takes REAL affinity on SQLite (its rules match on
    -- "DOUB"), so it is portable AND the same width on both.
    value_number      DOUBLE PRECISION,
    value_text        TEXT,
    value_bool        INTEGER CHECK (value_bool IS NULL OR value_bool IN (0, 1)),
    missing_reason    TEXT    CHECK (missing_reason IS NULL OR missing_reason IN
        ('not_collected','not_applicable','not_yet_known','suppressed_privacy',
         'suppressed_legal','source_unavailable','failed_validation',
         'withheld_by_operator','unresolved_identity')),
    event_time        TEXT,
    receipt_time      TEXT    NOT NULL,
    receipt_sequence  INTEGER NOT NULL,
    quality           TEXT    NOT NULL CHECK (quality IN
        ('trusted','provisional','repaired','suspect','conflicted')),
    confidence        DOUBLE PRECISION CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
    repair_kind       TEXT    NOT NULL CHECK (repair_kind IN
        ('none','unit_normalised','timezone_resolved','deduplicated','imputed',
         'range_clamped','code_mapped','parsed_from_free_text','manually_corrected')),
    repairs_fact_id   TEXT,
    repair_note       TEXT,
    sensitivity       TEXT    NOT NULL CHECK (sensitivity IN
        ('operational','identity','precise_location','free_text')),
    special_category  INTEGER NOT NULL CHECK (special_category IN (0, 1)),
    legal_basis       TEXT    NOT NULL CHECK (legal_basis IN
        ('contract_performance','legal_obligation','legitimate_interest','consent',
         'vital_interest','public_task','anonymised_aggregate','not_established')),
    source_system     TEXT    NOT NULL,
    source_record_id  TEXT,
    -- A value XOR a missingness reason.
    CHECK ((value_kind = 'absent' AND missing_reason IS NOT NULL)
        OR (value_kind <> 'absent' AND missing_reason IS NULL)),
    -- The typed column matching value_kind is the one that is populated.
    CHECK ((value_kind = 'number' AND value_number IS NOT NULL AND value_text IS NULL AND value_bool IS NULL)
        OR (value_kind = 'text'   AND value_text   IS NOT NULL AND value_number IS NULL AND value_bool IS NULL)
        OR (value_kind = 'bool'   AND value_bool   IS NOT NULL AND value_number IS NULL AND value_text IS NULL)
        OR (value_kind = 'absent' AND value_number IS NULL AND value_text IS NULL AND value_bool IS NULL)),
    -- An observation cannot be received before it happens. This is the
    -- database's half of the deduction that makes the snapshot's past-only
    -- property a theorem rather than a filter (see provenance.py). Two clauses:
    -- an observation carrying a VALUE must say when it was observed, and any
    -- observation time present must not be later than the receipt. An observation
    -- recording an ABSENCE needs no time -- there was nothing observed to time,
    -- and forcing one would make callers invent it.
    CHECK (fact_class <> 'observation' OR value_kind = 'absent'
        OR event_time IS NOT NULL),
    CHECK (fact_class <> 'observation' OR event_time IS NULL
        OR event_time <= receipt_time),
    -- Repair lineage points BACKWARD only; a repaired value must say so.
    CHECK ((repair_kind = 'none' AND repairs_fact_id IS NULL)
        OR (repair_kind <> 'none' AND quality = 'repaired')),
    CHECK (repairs_fact_id IS NULL OR repairs_fact_id <> fact_id),
    -- Health-adjacent data on no stated basis at all is not a footing.
    CHECK (special_category = 0 OR legal_basis <> 'not_established')
);

-- ---------------------------------------------------------------------------
-- 5. Events: what the operational world did.
--    ingest_lag_seconds is STORED, not derived, and beyond 300 seconds a row
--    must name a reason. Late arrival is declared, never hidden -- the same
--    discipline the canonical lifecycle record adopted after the 2026-07-26
--    audit. The gap's distribution is a real property of an operator: one whose
--    no-shows arrive six hours late cannot support a same-day no-show model,
--    and finding that out from the data is cheaper than from a failed pilot.
-- ---------------------------------------------------------------------------
CREATE TABLE ontology_events (
    event_id            TEXT    NOT NULL PRIMARY KEY,
    tenant_id           TEXT    NOT NULL,
    event_kind          TEXT    NOT NULL CHECK (event_kind IN
        ('booking_created','booking_amended','window_negotiated','assignment_created',
         'assignment_moved','vehicle_delayed','vehicle_unavailable','rider_cancelled',
         'rider_no_showed','dispatcher_overrode','arrival','pickup','dropoff',
         'trip_denied','trip_missed','policy_changed')),
    subject_kind        TEXT    NOT NULL,
    subject_id          TEXT    NOT NULL,
    occurred_at         TEXT    NOT NULL,
    receipt_time        TEXT    NOT NULL,
    receipt_sequence    INTEGER NOT NULL,
    ingest_lag_seconds  DOUBLE PRECISION NOT NULL CHECK (ingest_lag_seconds >= 0.0),
    late_arrival_reason TEXT    CHECK (late_arrival_reason IS NULL OR late_arrival_reason IN
        ('batch_export','manual_entry','backfill','source_outage','correction','unknown')),
    actor_kind          TEXT    NOT NULL CHECK (actor_kind IN
        ('system','human','human_on_behalf_of_system')),
    actor_ref           TEXT    NOT NULL,
    reason_codes        TEXT    NOT NULL DEFAULT '[]',
    payload             TEXT    NOT NULL DEFAULT '{}',
    prev_hash           TEXT,
    hash                TEXT    NOT NULL,
    CHECK (occurred_at <= receipt_time),
    CHECK (ingest_lag_seconds <= 300.0 OR late_arrival_reason IS NOT NULL)
);

-- ---------------------------------------------------------------------------
-- 6. Identity resolutions: match candidates retained WITH probabilities.
--    The candidate set is canonical JSON in one TEXT column, the same
--    convention decision_events.payload and vehicles.accessibility_equipment
--    already use in packages/canonical -- a child table would buy ordering
--    guarantees the canonical JSON already provides.
--    resolved_object_id NULL means UNRESOLVED, which is an honest state and not
--    an error: forcing a 0.61/0.39 match into one record silently attributes a
--    trip to the wrong rider and is not recoverable once trained on.
-- ---------------------------------------------------------------------------
CREATE TABLE ontology_identity_resolutions (
    candidate_set_id   TEXT    NOT NULL PRIMARY KEY,
    tenant_id          TEXT    NOT NULL,
    subject_kind       TEXT    NOT NULL,
    source_system      TEXT    NOT NULL,
    source_record_id   TEXT    NOT NULL,
    candidates_json    TEXT    NOT NULL,
    resolved_object_id TEXT,
    resolution_rule    TEXT,
    receipt_time       TEXT    NOT NULL,
    receipt_sequence   INTEGER NOT NULL,
    CHECK ((resolved_object_id IS NULL AND resolution_rule IS NULL)
        OR (resolved_object_id IS NOT NULL AND resolution_rule IS NOT NULL))
);

-- ---------------------------------------------------------------------------
-- 7. Snapshots. NOTE WHAT IS **NOT** STORED: the admitted facts themselves.
--    A snapshot row stores its boundary (as_of), its scope, its purpose and the
--    content hash it had when taken. Reloading RE-DERIVES the content from the
--    fact/relationship/event tables with the same `receipt_time < as_of`
--    predicate and compares hashes.
--
--    This is deliberate and it is the strongest single property in the packet:
--    because receipt monotonicity forbids anything appearing before an
--    already-taken boundary, a re-derivation must reproduce the same content --
--    so the reload path is a LEAK DETECTOR, not merely a read. Storing the fact
--    list instead would make reload a tautology that could never fail.
-- ---------------------------------------------------------------------------
CREATE TABLE ontology_snapshots (
    snapshot_id      TEXT    NOT NULL PRIMARY KEY,
    tenant_id        TEXT    NOT NULL,
    as_of            TEXT    NOT NULL,
    purpose          TEXT    NOT NULL CHECK (purpose IN
        ('operational_dispatch','model_training','evidence_export','replay')),
    scope_json       TEXT    NOT NULL,
    content_hash     TEXT    NOT NULL,
    receipt_time     TEXT    NOT NULL,
    receipt_sequence INTEGER NOT NULL,
    -- A snapshot cannot be taken as of the future.
    CHECK (as_of <= receipt_time)
);

-- ---------------------------------------------------------------------------
-- 8. Actions: typed, permissioned operations. The row a learner trains on.
--    input_snapshot_hash pins the exact information set, not merely a pointer:
--    pydantic's model_copy(update=...) skips validators, so a forged snapshot
--    is one line away, and only the hash catches it.
-- ---------------------------------------------------------------------------
CREATE TABLE ontology_actions (
    action_id             TEXT    NOT NULL PRIMARY KEY,
    tenant_id             TEXT    NOT NULL,
    action_kind           TEXT    NOT NULL CHECK (action_kind IN
        ('accept_request','negotiate_request','assign','reassign','hold_capacity',
         'reposition_capacity','combine_trips','call_in_spare_capacity',
         'escalate_accessibility_risk','approve_recommendation','reject_recommendation')),
    subject_kind          TEXT    NOT NULL,
    subject_id            TEXT    NOT NULL,
    input_snapshot_id     TEXT    NOT NULL REFERENCES ontology_snapshots(snapshot_id),
    input_snapshot_hash   TEXT    NOT NULL,
    input_snapshot_as_of  TEXT    NOT NULL,
    policy_id             TEXT    NOT NULL,
    policy_version        INTEGER NOT NULL CHECK (policy_version >= 1),
    alternatives_json     TEXT    NOT NULL DEFAULT '[]',
    prediction_json       TEXT,
    verifier_verdict      TEXT    NOT NULL CHECK (verifier_verdict IN
        ('pass','fail','warn','not_run','unavailable')),
    verifier_name         TEXT    NOT NULL,
    verifier_version      TEXT    NOT NULL,
    violated_rules_json   TEXT    NOT NULL DEFAULT '[]',
    override_justification TEXT,
    authority_kind        TEXT    NOT NULL CHECK (authority_kind IN
        ('system','human','human_on_behalf_of_system')),
    authority_ref         TEXT    NOT NULL,
    authority_role        TEXT    NOT NULL,
    authority_permissions_json TEXT NOT NULL,
    authority_on_behalf_of TEXT,
    decided_at            TEXT    NOT NULL,
    receipt_time          TEXT    NOT NULL,
    receipt_sequence      INTEGER NOT NULL,
    reason_codes          TEXT    NOT NULL DEFAULT '[]',
    prev_hash             TEXT,
    hash                  TEXT    NOT NULL,
    -- A decision cannot cite an information set from after it was taken.
    CHECK (input_snapshot_as_of <= decided_at),
    CHECK (decided_at <= receipt_time),
    -- A failing verifier that was overridden must say why.
    CHECK (verifier_verdict <> 'fail' OR override_justification IS NOT NULL)
);

-- ---------------------------------------------------------------------------
-- 9. Outcomes: separate rows with their own receipt times, never a column on
--    the action. Writing an outcome onto the action would be a mutation of a
--    row snapshots have already admitted, and would make the action's hash
--    unstable. Separation also allows the several outcomes one action really
--    has -- 14 minutes late, a complaint at +3 days, a re-bill at +1 month.
--    Because an outcome's receipt time is necessarily later than its action's,
--    an outcome is invisible to any snapshot at or before the decision. That is
--    the mechanism by which labels cannot leak into features, and it is a
--    consequence of receipt monotonicity rather than a rule anything enforces.
-- ---------------------------------------------------------------------------
CREATE TABLE ontology_action_outcomes (
    outcome_id       TEXT    NOT NULL PRIMARY KEY,
    tenant_id        TEXT    NOT NULL,
    action_id        TEXT    NOT NULL REFERENCES ontology_actions(action_id),
    metric           TEXT    NOT NULL,
    value            DOUBLE PRECISION NOT NULL,
    observed_at      TEXT    NOT NULL,
    receipt_time     TEXT    NOT NULL,
    receipt_sequence INTEGER NOT NULL,
    horizon_seconds  DOUBLE PRECISION NOT NULL CHECK (horizon_seconds >= 0.0),
    source_system    TEXT    NOT NULL,
    source_record_id TEXT,
    CHECK (observed_at <= receipt_time)
);

-- Indexes supporting the ONE query shape that matters: the point-in-time cut.
-- (tenant_id, subject_id, receipt_time) is exactly the predicate
-- OntologyStore.snapshot_at issues, in that order.
CREATE INDEX idx_ontology_facts_asof
    ON ontology_facts (tenant_id, subject_id, receipt_time, receipt_sequence);
CREATE INDEX idx_ontology_relationships_asof
    ON ontology_relationships (tenant_id, subject_id, receipt_time);
CREATE INDEX idx_ontology_events_asof
    ON ontology_events (tenant_id, subject_id, receipt_time);
CREATE INDEX idx_ontology_receipt_log_time
    ON ontology_receipt_log (tenant_id, receipt_time);
