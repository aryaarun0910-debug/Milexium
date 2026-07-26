"""Re-derivation of a stored lifecycle chain -- the CHECKER, not the writer.

WHAT THIS IS FOR. The decision-event ledger has been hash-chained and
independently re-verifiable since ADR-0003. The lifecycle record -- the table
that is presented as the answer to "what happened, who decided, and when?" -- had
no chain at all until MX-A-LIFECYCLE-IMMUTABILITY-012, and the audit's finding
was not only the missing chain: it was that the LEDGER'S credibility was being
read as though it covered this table too. This module closes that by giving the
lifecycle record the same construction and, more importantly, the same explicit
statement of what the construction is worth.

WHAT IT PROVES, AND WHAT IT DOES NOT. This is tamper EVIDENCE, not
authentication. There is no secret in the hash and no signature over it, so a
party who can write rows can also recompute hashes: a forger with INSERT rights
and this source code can append a chain-valid row. What it catches is any change
made WITHOUT recomputing -- a direct UPDATE, an edited backup, a restore from a
tampered dump, a replica that silently diverged, a truncated or re-ordered
chain -- and any change to an EARLIER row, because every later row's hash depends
on it and correcting them all requires rewriting the whole chain.

Making the record un-forgeable by a writer needs something this repository does
not have: signed checkpoint roots anchored outside the database, or a
write-once medium. Nothing here should be described as though it did.

WHY IT LIVES IN ITS OWN MODULE. Blueprint 19: checkers stay separate from
generators. `lifecycle.py` builds and appends; this module only reads back and
recomputes. It shares `lifecycle_transition_hash` with the writer deliberately --
a second implementation of the hash would be a second thing to get wrong, and
ADR-0003 made that function normative -- but it shares nothing else, and in
particular it does NOT go through `RequestTransition`. That model already
refuses a row whose hash disagrees with its contents, so verifying reconstructed
models would be asking the thing that cannot hold a bad row whether it is holding
one. This reads RAW STORED COLUMNS and reports; it raises nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from packages.canonical.lifecycle import (
    LateRecordingReason,
    TimeWindow,
    lifecycle_transition_hash,
    parse_fixed_utc,
    transition_payload,
)
from packages.canonical.state_machine import ServiceRequestState
from packages.canonical.vocab import ReasonCode


@dataclass(frozen=True)
class LifecycleChainVerification:
    """The verdict on one request's stored chain.

    `ok` is False if ANY finding was recorded. Findings are strings naming the
    row and what is wrong with it, because a verifier that returns a bare boolean
    forces its caller to re-derive the reason it already knew.
    """

    ok: bool
    rows_checked: int
    findings: tuple[str, ...]

    def __bool__(self) -> bool:  # pragma: no cover - convenience only
        return self.ok


def _window(start: str | None, end: str | None) -> TimeWindow | None:
    if start is None and end is None:
        return None
    if start is None or end is None:
        raise ValueError("a stored window has exactly one bound")
    return TimeWindow(start=parse_fixed_utc(start), end=parse_fixed_utc(end))


def verify_lifecycle_chain(rows: list[dict]) -> LifecycleChainVerification:
    """Re-derive a request's chain from RAW STORED ROWS, in `sequence` order.

    Each row is the column mapping the stores return from
    `raw_lifecycle_rows()` -- deliberately raw, so what is being checked is the
    stored bytes rather than this package's own round-trip.

    Five independent things are checked, and they catch different forgeries:

      1. **Sequence contiguity from 1.** A deleted row leaves a gap; a chain that
         starts at 2 has had its beginning removed. Neither is visible from
         hashes alone, because the remaining rows still link to each other.
      2. **The genesis link.** Row 1 has no `prev_hash` and no other row may lack
         one -- otherwise a chain can be silently re-rooted at any position.
      3. **Per-row content hash.** Every asserted field is re-hashed and compared
         with the stored hash. This is what a direct UPDATE fails.
      4. **Linkage.** Each row's `prev_hash` must equal the previous row's `hash`,
         so a row cannot be swapped for another validly-hashed row.
      5. **State-machine continuity.** Each `from_state` must be the previous
         `to_state`, and `decided_at` must not go backwards. A forger with INSERT
         rights can compute correct hashes, so these are what makes an APPENDED
         row visible: an appended denial that does not continue the stored chain
         is reported here even though its hash is perfect.

    Note what is NOT checked here: transition legality against
    SERVICE_REQUEST_TRANSITIONS. That is `check_transition`'s job and it already
    runs on every read through the store, which raises rather than reports.
    """
    findings: list[str] = []
    ordered = sorted(rows, key=lambda row: row["sequence"])

    previous: dict | None = None
    for index, row in enumerate(ordered, start=1):
        label = f"sequence {row['sequence']} (transition {row['transition_id']})"

        if row["sequence"] != index:
            findings.append(
                f"{label}: expected chain position {index} -- the chain is not "
                "contiguous from 1, so a row has been removed or never landed"
            )

        if (row["sequence"] == 1) != (row["prev_hash"] is None):
            findings.append(
                f"{label}: prev_hash is {row['prev_hash']!r}, which does not match "
                "its chain position -- only the first transition has no predecessor"
            )

        payload = transition_payload(
            transition_id=row["transition_id"],
            tenant_id=row["tenant_id"],
            request_id=row["request_id"],
            from_state=ServiceRequestState(row["from_state"]),
            to_state=ServiceRequestState(row["to_state"]),
            decided_at=parse_fixed_utc(row["decided_at"]),
            recorded_at=parse_fixed_utc(row["recorded_at"]),
            actor_type=row["actor_type"],
            actor_id=row["actor_id"],
            reason_codes=tuple(ReasonCode(code) for code in json.loads(row["reason_codes"])),
            requested_window=_window(
                row["requested_window_start"], row["requested_window_end"]
            ),
            negotiated_window=_window(
                row["negotiated_window_start"], row["negotiated_window_end"]
            ),
            late_recording_reason=(
                None
                if row["late_recording_reason"] is None
                else LateRecordingReason(row["late_recording_reason"])
            ),
        )
        expected = lifecycle_transition_hash(
            prev_hash=row["prev_hash"],
            payload=payload,
            sequence=row["sequence"],
            request_id=row["request_id"],
        )
        if row["hash"] != expected:
            findings.append(
                f"{label}: stored hash {row['hash']!r} does not match its contents "
                f"(recomputed {expected!r}) -- this row was altered after it was written"
            )

        if previous is not None:
            if row["prev_hash"] != previous["hash"]:
                findings.append(
                    f"{label}: prev_hash {row['prev_hash']!r} does not link to the "
                    f"preceding row's hash {previous['hash']!r} -- the chain is broken "
                    "or a row has been substituted"
                )
            if row["from_state"] != previous["to_state"]:
                findings.append(
                    f"{label}: starts from {row['from_state']!r} but the preceding "
                    f"transition ended in {previous['to_state']!r} -- this row does "
                    "not continue the recorded history"
                )
            if parse_fixed_utc(row["decided_at"]) < parse_fixed_utc(previous["decided_at"]):
                findings.append(
                    f"{label}: decided at {row['decided_at']} which is BEFORE the "
                    f"decision it follows ({previous['decided_at']})"
                )

        # The lag column is a measurement of the two clocks stored beside it, so a
        # disagreement means one of the three was edited. Checked here as well as
        # in the model because this path never builds a model.
        measured = (
            parse_fixed_utc(row["recorded_at"]) - parse_fixed_utc(row["decided_at"])
        ).total_seconds()
        if abs(float(row["ingest_lag_seconds"]) - measured) > 1e-6:
            findings.append(
                f"{label}: stored ingest_lag_seconds {row['ingest_lag_seconds']!r} "
                f"disagrees with its own timestamps ({measured!r}s apart)"
            )

        previous = row

    return LifecycleChainVerification(
        ok=not findings, rows_checked=len(ordered), findings=tuple(findings)
    )


def newest_recorded_at(rows: list[dict]) -> datetime | None:
    """The latest transaction time in a set of raw rows, or None if empty.

    Small helper for callers that want to state how fresh a verified chain is
    without re-parsing the fixed-width timestamps themselves.
    """
    if not rows:
        return None
    return max(parse_fixed_utc(row["recorded_at"]) for row in rows)
