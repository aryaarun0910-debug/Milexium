"""Golden-path end-to-end demo (Phase 2, item 1).

The single most reusable proof artifact: one runnable script that drives the
whole Milexium loop -- ingest -> forecast -> decide -> evidence -> replay ->
export -- on REAL public data (not the fictional reference agency), printing
each step and writing independently-verifiable artifacts.

    py -3 -m demo.golden_path

This package IMPORTS the shipped packages (packages/connect, forecast, decide,
sdk, evidence, replay, core, canonical) and adds no new domain logic -- it is a
composition/demonstration layer. Every claim it prints is labelled Demonstrated,
never Validated; it makes the real-vs-synthetic boundary visible in its own
output rather than hiding it.

Import the entry points directly from the submodule -- the package deliberately
does NOT eagerly import `demo.golden_path` (which pulls in xgboost/duckdb) at
package-import time, and that also keeps `py -3 -m demo.golden_path` free of the
"module already in sys.modules" runtime warning:

    from demo.golden_path import run_golden_path, GoldenPathResult
"""

