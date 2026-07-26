"""Attribution: the type that makes Argus's prohibition checkable.

    Argus must never invent a fact, constraint, reason or recommendation.
    Argus renders authority; it does not manufacture authority.

A prohibition that lives only in a docstring is a hope. This module turns it
into a data structure: nothing reaches the page except as a `Figure`, and a
`Figure` cannot be constructed without naming where its value came from. The
source is not a footnote -- `render.py` prints it under every number, so a
viewer asking "where did that come from?" reads the answer rather than
trusting the page.

THE FIVE ORIGINS, and why the list is closed.

    themis      a governed record: canonical state, an ingest verdict, a
                ledger event. Argus read it; Argus did not decide it.
    metis       a model or solver output: a scheduling verdict, a checker's
                reason code, a foreclosure estimate, a drift verdict.
    aletheia    evidence: an evidence packet, a teardown, a re-derivation.
    corpus      a committed file in the governed data corpus, cited by repo
                path and SHA-256 (real public data, or a synthetic file that
                says so in its own name).
    scenario    a DECLARED input to the synthetic scenario -- a modelling
                assumption with no authority behind it at all. Separated from
                the other four precisely so a reader can see which numbers
                rest on one, and so a suite can require that every such value
                is disclosed rather than blended into the governed ones.
    argus       the page measuring ITSELF: build time, figure counts. Not a
                claim about transport at all, and kept apart from the domain
                origins so it can never be mistaken for one.

`derived` is deliberately NOT an origin. A count of governed records is still
governed; an arithmetic mean of declared inputs is still declared. Attribution
follows the weakest input, which `Figure.derived_from` enforces by construction
rather than by the author remembering to downgrade it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Sequence

Origin = Literal["themis", "metis", "aletheia", "corpus", "scenario", "argus"]

#: Ordered weakest-last. `Figure.derived_from` takes the maximum, so a figure
#: mixing a governed count with a declared assumption is attributed to the
#: assumption -- the honest direction, and the one an author would forget.
#: `argus` sorts first and can therefore never win a mix: build metadata is not
#: a claim about anything, so it must not be able to relabel one.
_ORIGIN_STRENGTH: dict[str, int] = {
    "argus": -1,
    "themis": 0,
    "metis": 1,
    "aletheia": 2,
    "corpus": 3,
    "scenario": 4,
}

ORIGIN_LABELS: dict[str, str] = {
    "themis": "Themis — governed reality",
    "metis": "Metis — model output",
    "aletheia": "Aletheia — evidence",
    "corpus": "Governed corpus",
    "scenario": "DECLARED scenario input",
    "argus": "Argus — this page about itself",
}


class UnattributedFigure(ValueError):
    """A figure reached the page without naming where its value came from."""


@dataclass(frozen=True)
class Source:
    """Where one displayed value came from, in enough detail to go and check.

    `citation` is the thing a reader would open: a dotted Python path into the
    layer that computed it, or a repo-relative file path. `detail` is the
    sentence that says what was read, not what it means.
    """

    origin: Origin
    citation: str
    detail: str
    sha256: str | None = None

    def __post_init__(self) -> None:
        if self.origin not in _ORIGIN_STRENGTH:
            raise UnattributedFigure(f"unknown origin {self.origin!r}")
        if not self.citation.strip():
            raise UnattributedFigure(
                f"a {self.origin} source must cite something openable; got an empty citation"
            )
        if not self.detail.strip():
            raise UnattributedFigure(
                f"source {self.citation!r} carries no detail; a citation without a "
                "statement of what was read is not an attribution"
            )

    @property
    def label(self) -> str:
        return ORIGIN_LABELS[self.origin]

    def to_record(self) -> dict:
        record = {"origin": self.origin, "citation": self.citation, "detail": self.detail}
        if self.sha256 is not None:
            record["sha256"] = self.sha256
        return record


@dataclass(frozen=True)
class Figure:
    """One number, string or verdict on the page, inseparable from its source.

    `display` is the exact text rendered, so a test can assert the page shows
    what the record says without re-implementing the formatting -- the failure
    mode where a page and its sidecar drift apart is the one this closes.
    """

    key: str
    label: str
    display: str
    source: Source
    note: str | None = None
    value: object | None = None

    def __post_init__(self) -> None:
        if not self.display.strip():
            raise UnattributedFigure(f"figure {self.key!r} renders as empty text")

    @classmethod
    def derived_from(
        cls,
        key: str,
        label: str,
        display: str,
        sources: Sequence[Source],
        *,
        detail: str,
        note: str | None = None,
        value: object | None = None,
    ) -> "Figure":
        """A figure computed from several sources, attributed to the weakest.

        Used for the handful of values that are arithmetic over other
        displayed values (a share, a mean, a difference). The composite source
        cites every input, and its origin is the weakest of them -- so a
        percentage of governed counts stays `themis`, and the same percentage
        with a declared assumption in it becomes `scenario`.
        """
        if not sources:
            raise UnattributedFigure(f"figure {key!r} was derived from no sources at all")
        weakest = max(sources, key=lambda s: _ORIGIN_STRENGTH[s.origin])
        return cls(
            key=key,
            label=label,
            display=display,
            note=note,
            value=value,
            source=Source(
                origin=weakest.origin,
                citation=" + ".join(dict.fromkeys(s.citation for s in sources)),
                detail=detail,
            ),
        )

    def to_record(self) -> dict:
        record: dict = {
            "key": self.key,
            "label": self.label,
            "display": self.display,
            "source": self.source.to_record(),
        }
        if self.note is not None:
            record["note"] = self.note
        if self.value is not None:
            record["value"] = self.value
        return record


@dataclass
class FigureLedger:
    """Every figure the page will show, in the order it was computed.

    Exists so the artifact can carry a machine-checkable list of its own
    contents. The conformance suite reads it and asserts that each `display`
    string and each citation actually appears in the rendered HTML, which is
    the only way to keep "every number carries its source" true after the next
    person edits the template.
    """

    figures: list[Figure] = field(default_factory=list)

    def add(self, figure: Figure) -> Figure:
        if any(existing.key == figure.key for existing in self.figures):
            raise UnattributedFigure(f"duplicate figure key {figure.key!r}")
        self.figures.append(figure)
        return figure

    def emit(
        self,
        key: str,
        label: str,
        display: str,
        source: Source,
        *,
        note: str | None = None,
        value: object | None = None,
    ) -> Figure:
        return self.add(
            Figure(key=key, label=label, display=display, source=source, note=note, value=value)
        )

    def __len__(self) -> int:
        return len(self.figures)

    def to_records(self) -> list[dict]:
        return [figure.to_record() for figure in self.figures]

    def by_origin(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for figure in self.figures:
            counts[figure.source.origin] = counts.get(figure.source.origin, 0) + 1
        return dict(sorted(counts.items()))
