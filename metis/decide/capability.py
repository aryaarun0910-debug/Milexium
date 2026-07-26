"""Optional-solver capability probing (Program F, v0.3).

The portfolio (`metis.decide.portfolio`) is allowed to contain strategies
whose third-party solver may simply not be installed on the machine running it.
That is a *capability question*, not an error, and it must be answered in exactly
one place so every caller answers it the same way.

The rule this module enforces:

- A missing optional dependency makes a strategy UNAVAILABLE. It is recorded in
  the portfolio report as unavailable-with-a-reason and skipped. It is never
  silently dropped (which would make the report a lie by omission), never
  emulated by a hand-rolled substitute wearing the same name, and never allowed
  to fail the run.
- The probe is a real import of the exact symbol the backend needs
  (`ortools.sat.python.cp_model`), not a `find_spec` guess. A wheel that
  installs but cannot load -- the usual shape of an ABI mismatch on a new Python
  -- reports unavailable with the loader's own message, which is the diagnostic
  a reader actually needs.
- The probe result is cached per process: importing OR-Tools costs ~0.2s and a
  portfolio may consult the capability many times.

Recorded as of this packet: `ortools` 9.15.6755 publishes a `cp314` wheel and
imports cleanly on CPython 3.14.2 (win_amd64), so CP-SAT is AVAILABLE here. The
unavailable path is still load-bearing -- it is what keeps the suite green on a
machine or CI image without the wheel -- and is exercised by an injected-failure
test rather than being left as untested prose.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SolverCapability:
    """Whether an optional third-party solver can actually be used here.

    `detail` is the honest reason: the version string when present, or the real
    exception text when the import failed. A caller writing a report copies this
    verbatim rather than paraphrasing it into "not installed", which would be
    wrong for the ABI-mismatch case.
    """

    name: str
    available: bool
    version: str | None
    detail: str

    def require(self) -> None:
        """Raise if the solver is unusable. For entry points that are documented
        as needing it, so the failure names the dependency instead of surfacing
        as an AttributeError three frames deeper."""
        if not self.available:
            raise SolverUnavailable(f"{self.name} is not available: {self.detail}")


class SolverUnavailable(RuntimeError):
    """An optional solver backend was called on a machine that cannot run it."""


_ORTOOLS_CACHE: SolverCapability | None = None


def ortools_capability(*, refresh: bool = False) -> SolverCapability:
    """Probe for a usable OR-Tools CP-SAT. Cached; `refresh=True` re-probes
    (used only by the test that proves the unavailable path is real)."""
    global _ORTOOLS_CACHE
    if _ORTOOLS_CACHE is not None and not refresh:
        return _ORTOOLS_CACHE
    try:
        import ortools  # noqa: F401
        from ortools.sat.python import cp_model  # noqa: F401
    except Exception as exc:  # ImportError, or an ABI/loader failure on a new Python
        cap = SolverCapability(
            name="ortools-cpsat",
            available=False,
            version=None,
            detail=f"{type(exc).__name__}: {exc}",
        )
    else:
        version = getattr(ortools, "__version__", None) or "unknown"
        cap = SolverCapability(
            name="ortools-cpsat",
            available=True,
            version=str(version),
            detail=f"ortools {version} imported successfully",
        )
    _ORTOOLS_CACHE = cap
    return cap


def cpsat_available() -> bool:
    return ortools_capability().available
