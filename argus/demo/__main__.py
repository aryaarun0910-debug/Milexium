"""`py -3 -m argus.demo` runs the evidence walkthrough.

The other two entry points, both documented in forge/knowledge/docs/DEMO.md:
  py -3 -m argus.demo.verify_pack aletheia/artifacts/demo-walkthrough   # re-derive the bundle
  py -3 -m argus.demo.golden_path                              # the real-data demo,
                                                         # skips without the
                                                         # gitignored inputs
"""

from __future__ import annotations

from argus.demo.walkthrough import main

if __name__ == "__main__":
    raise SystemExit(main())
