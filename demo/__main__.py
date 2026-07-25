"""`py -3 -m demo` runs the evidence walkthrough.

The other two entry points, both documented in docs/DEMO.md:
  py -3 -m demo.verify_pack artifacts/demo-walkthrough   # re-derive the bundle
  py -3 -m demo.golden_path                              # the real-data demo,
                                                         # skips without the
                                                         # gitignored inputs
"""

from __future__ import annotations

from demo.walkthrough import main

if __name__ == "__main__":
    raise SystemExit(main())
