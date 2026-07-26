"""Generic Milexium Connect adapter contract (Program B, first slice).

blueprint/03-connect-and-standards.md defines the full adapter surface
(inspect/validate_raw/map/reconcile/incremental_cursor/export) and requires
that every import report "accepted, rejected, defaulted, and quarantined row
counts" plus "semantic-loss warnings" rather than silently dropping data.
This module implements only the minimum slice of that contract needed for
one real adapter: mapping a single raw row, either into a canonical record
(with any semantic-loss notes attached) or into an explicit quarantine.
The rest of the adapter surface remains Specified, not Exists.
"""

from __future__ import annotations

from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

CanonicalT = TypeVar("CanonicalT", bound=BaseModel)


class SemanticLossRecord(BaseModel):
    """One source field that did not map cleanly onto a canonical field.

    Covers the three cases blueprint/03 calls out: an extra/vendor field
    (`unmapped_extension`), a value that had to be narrowed or defaulted
    (`dropped`/`truncated`), and a value mapped only by an explicit,
    recorded assumption (`coerced`) -- never a silent guess.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_field: str
    source_value: str | None
    reason: str
    disposition: str = Field(pattern="^(dropped|truncated|coerced|unmapped_extension)$")


class QuarantinedRow(BaseModel):
    """A source row that could not become a canonical record at all.

    The raw row is preserved verbatim so a quarantined row can be inspected,
    fixed upstream, and re-run -- never just discarded (mapping rule 7:
    "quarantine impossible or policy-sensitive records rather than guessing").
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_row: dict
    reason: str
    failed_field: str | None = None


class AdapterResult(BaseModel, Generic[CanonicalT]):
    """Exactly one of a mapped canonical record or a quarantine -- never
    both, never neither, so a caller can never mistake a missing quarantine
    for a silent drop.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    record: CanonicalT | None = None
    semantic_loss: tuple[SemanticLossRecord, ...] = ()
    quarantine: QuarantinedRow | None = None

    @model_validator(mode="after")
    def _exactly_one_outcome(self) -> "AdapterResult":
        if (self.record is None) == (self.quarantine is None):
            raise ValueError(
                "AdapterResult must set exactly one of record or quarantine, never both or neither"
            )
        if self.quarantine is not None and self.semantic_loss:
            raise ValueError("a quarantined row cannot also carry semantic-loss notes for a record")
        return self

    @property
    def is_quarantined(self) -> bool:
        return self.quarantine is not None


class SourceAdapter(Protocol[CanonicalT]):
    """The one method this slice requires every adapter to implement.

    Full contract surface (inspect/validate_raw/map/reconcile/
    incremental_cursor/export, per blueprint/03-connect-and-standards.md)
    is Specified, not Exists, here -- adding it is future Program B work,
    not part of this first slice.
    """

    def parse(self, raw_row: dict) -> AdapterResult[CanonicalT]: ...


def parse_batch(
    adapter: SourceAdapter[CanonicalT], raw_rows: list[dict]
) -> list[AdapterResult[CanonicalT]]:
    """Run an adapter over a batch, one row at a time.

    A single row raising an uncaught exception must not kill the batch: it
    is caught here and turned into an explicit quarantine, same as any other
    unmappable row.
    """

    results: list[AdapterResult[CanonicalT]] = []
    for raw_row in raw_rows:
        try:
            results.append(adapter.parse(raw_row))
        except Exception as exc:
            results.append(
                AdapterResult(
                    quarantine=QuarantinedRow(
                        raw_row=raw_row,
                        reason=f"adapter raised {type(exc).__name__}: {exc}",
                    )
                )
            )
    return results
