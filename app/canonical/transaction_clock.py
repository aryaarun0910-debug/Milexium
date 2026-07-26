"""The ONE place the canonical write path is allowed to read a wall clock.

WHY THIS FILE EXISTS AT ALL. `lifecycle.py`, `storage.py` and
`postgres_storage.py` are asserted clock-free by AST over their own parsed
source (`test_no_module_on_the_write_path_reads_a_clock`), and that assertion is
load-bearing: `decided_at` -- the instant a dispatcher or the scheduler actually
reached a conclusion -- must come from the caller, because a value the writer
invents is the "reconstructed afterwards" artefact this record exists not to be.

But MX-A-LIFECYCLE-IMMUTABILITY-012 found the mirror-image defect in the OTHER
clock. `recorded_at` -- transaction time, when the row entered Milexium -- was
also a caller argument, so the whole "bitemporal" claim rested on two assertions
by the same party, ordered only relative to each other. An external audit
inserted a 2020-01-01 decision "recorded" one second later and the system took
it. Transaction time that the caller supplies is not transaction time.

So exactly one of the two clocks has to be read by the WRITER, and putting that
read in its own module rather than inline is deliberate:

  * the three write-path modules stay literally clock-free, so the AST assertion
    protecting `decided_at` keeps its full strength and does not have to be
    weakened into "no clock except this one call", which is the shape that stops
    being checkable;
  * there is ONE line in the package that can be replaced to make every stamped
    time wrong, and it is a line a reviewer can find in a second;
  * a test can inject a clock here without any store growing a
    `clock=` parameter -- and a `clock=` parameter on `record_transition` would
    be exactly the hole that was just closed, since a caller could pass one.

WHAT THIS IS NOT. It is not a trusted timestamp. The process clock can be wrong,
and on a host an attacker controls it can be wrong on purpose. That is why the
value this returns is BOUNDED BY THE DATABASE on insert: both engines carry a
BEFORE INSERT trigger refusing any `recorded_at` more than
`RECORDED_AT_TOLERANCE_SECONDS` from the database server's own clock, so a writer
with a skewed or hostile clock cannot record a row at all rather than recording a
false one. Neither clock is externally attested; anchoring signed checkpoint
roots outside the database is what that would take, and this repository does not
have it.
"""

from __future__ import annotations

from datetime import datetime, timezone


def transaction_time() -> datetime:
    """The instant Milexium is writing, as a timezone-aware UTC datetime.

    Microsecond resolution matters here: an automated scheduler writes several
    transitions inside one second, and their `recorded_at` values are part of what
    distinguishes them.
    """
    return datetime.now(timezone.utc)
