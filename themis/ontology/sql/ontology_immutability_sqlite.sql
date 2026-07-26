-- SQLite half of the ontology's two structural invariants.
--
-- WHY THIS FILE EXISTS AT ALL. An external audit of this repository
-- (2026-07-26) found a table whose schema comment called it append-only because
-- "application code contains no update/delete path", then wrote a valid row,
-- issued a direct SQL UPDATE, committed it, and read the forged value back
-- through the normal API with no violation reported. A coding convention is not
-- a database invariant. Nothing in themis/ontology relies on one.
--
-- INVARIANT 1 -- APPEND-ONLY. Every ontology table rejects UPDATE and DELETE,
-- in the database, with SQLSTATE-style marker MX001 in the message. A
-- correction is a new row with a later receipt time; a retraction is a new row
-- naming what it retracts. Neither is ever an edit.
--
-- INVARIANT 2 -- RECEIPT MONOTONICITY (MX002/MX003). A receipt-log row whose
-- receipt_time is earlier than the tenant's current maximum is rejected, as is
-- one whose sequence is not exactly the next. This is the property that makes
-- an information set FINAL: once a snapshot at T has been taken, nothing can
-- afterwards appear before T, so the snapshot is permanently reproducible and
-- can never be retroactively enlarged. It is enforced here as well as in
-- themis/ontology/receipt.next_stamp precisely because a direct SQL insert
-- must be refused too -- Python-side monotonicity would be the same convention
-- the audit already broke.
--
-- WHAT THIS FILE DOES NOT BUY, STATED PLAINLY. On SQLite there is no privilege
-- separation: whoever holds the connection can `DROP TRIGGER`. The trigger
-- stops accidental and casual mutation, not a determined holder of the file.
-- The third layer -- the hash chain in ontology_receipt_log -- is what makes a
-- mutation that got past this DETECTABLE on read. Detection, not prevention, is
-- the honest claim for a single-file embedded database, and SQLite is the
-- argus/demo/reference engine here, not the production target (ADR-0004).

CREATE TRIGGER ontology_receipt_log_no_update BEFORE UPDATE ON ontology_receipt_log
BEGIN SELECT RAISE(ABORT, 'MX001 ontology_receipt_log is append-only: UPDATE refused'); END;
CREATE TRIGGER ontology_receipt_log_no_delete BEFORE DELETE ON ontology_receipt_log
BEGIN SELECT RAISE(ABORT, 'MX001 ontology_receipt_log is append-only: DELETE refused'); END;

CREATE TRIGGER ontology_objects_no_update BEFORE UPDATE ON ontology_objects
BEGIN SELECT RAISE(ABORT, 'MX001 ontology_objects is append-only: UPDATE refused'); END;
CREATE TRIGGER ontology_objects_no_delete BEFORE DELETE ON ontology_objects
BEGIN SELECT RAISE(ABORT, 'MX001 ontology_objects is append-only: DELETE refused'); END;

CREATE TRIGGER ontology_relationships_no_update BEFORE UPDATE ON ontology_relationships
BEGIN SELECT RAISE(ABORT, 'MX001 ontology_relationships is append-only: UPDATE refused'); END;
CREATE TRIGGER ontology_relationships_no_delete BEFORE DELETE ON ontology_relationships
BEGIN SELECT RAISE(ABORT, 'MX001 ontology_relationships is append-only: DELETE refused'); END;

CREATE TRIGGER ontology_facts_no_update BEFORE UPDATE ON ontology_facts
BEGIN SELECT RAISE(ABORT, 'MX001 ontology_facts is append-only: UPDATE refused'); END;
CREATE TRIGGER ontology_facts_no_delete BEFORE DELETE ON ontology_facts
BEGIN SELECT RAISE(ABORT, 'MX001 ontology_facts is append-only: DELETE refused'); END;

CREATE TRIGGER ontology_events_no_update BEFORE UPDATE ON ontology_events
BEGIN SELECT RAISE(ABORT, 'MX001 ontology_events is append-only: UPDATE refused'); END;
CREATE TRIGGER ontology_events_no_delete BEFORE DELETE ON ontology_events
BEGIN SELECT RAISE(ABORT, 'MX001 ontology_events is append-only: DELETE refused'); END;

CREATE TRIGGER ontology_identity_no_update BEFORE UPDATE ON ontology_identity_resolutions
BEGIN SELECT RAISE(ABORT, 'MX001 ontology_identity_resolutions is append-only: UPDATE refused'); END;
CREATE TRIGGER ontology_identity_no_delete BEFORE DELETE ON ontology_identity_resolutions
BEGIN SELECT RAISE(ABORT, 'MX001 ontology_identity_resolutions is append-only: DELETE refused'); END;

CREATE TRIGGER ontology_snapshots_no_update BEFORE UPDATE ON ontology_snapshots
BEGIN SELECT RAISE(ABORT, 'MX001 ontology_snapshots is append-only: UPDATE refused'); END;
CREATE TRIGGER ontology_snapshots_no_delete BEFORE DELETE ON ontology_snapshots
BEGIN SELECT RAISE(ABORT, 'MX001 ontology_snapshots is append-only: DELETE refused'); END;

CREATE TRIGGER ontology_actions_no_update BEFORE UPDATE ON ontology_actions
BEGIN SELECT RAISE(ABORT, 'MX001 ontology_actions is append-only: UPDATE refused'); END;
CREATE TRIGGER ontology_actions_no_delete BEFORE DELETE ON ontology_actions
BEGIN SELECT RAISE(ABORT, 'MX001 ontology_actions is append-only: DELETE refused'); END;

CREATE TRIGGER ontology_outcomes_no_update BEFORE UPDATE ON ontology_action_outcomes
BEGIN SELECT RAISE(ABORT, 'MX001 ontology_action_outcomes is append-only: UPDATE refused'); END;
CREATE TRIGGER ontology_outcomes_no_delete BEFORE DELETE ON ontology_action_outcomes
BEGIN SELECT RAISE(ABORT, 'MX001 ontology_action_outcomes is append-only: DELETE refused'); END;

-- INVARIANT 2. MAX() over an empty filtered set is NULL, and `x < NULL` is
-- NULL, so the WHEN clause is false for a tenant's first row -- no special case
-- needed. Equal receipt times are ACCEPTED (two rows can genuinely arrive in the
-- same microsecond and receipt_sequence still orders them); only a strictly
-- earlier one is refused.
CREATE TRIGGER ontology_receipt_monotonic BEFORE INSERT ON ontology_receipt_log
WHEN NEW.receipt_time < (
    SELECT MAX(receipt_time) FROM ontology_receipt_log WHERE tenant_id = NEW.tenant_id
)
BEGIN
    SELECT RAISE(ABORT, 'MX002 receipt time went backwards: refusing to insert a row before an already-taken snapshot boundary');
END;

CREATE TRIGGER ontology_receipt_sequence_gapless BEFORE INSERT ON ontology_receipt_log
WHEN NEW.receipt_sequence <> 1 + COALESCE(
    (SELECT MAX(receipt_sequence) FROM ontology_receipt_log WHERE tenant_id = NEW.tenant_id), 0
)
BEGIN
    SELECT RAISE(ABORT, 'MX003 receipt sequence is not the next in this order: a gap or a reused position would make the receipt order ambiguous');
END;
