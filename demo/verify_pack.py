"""Independently re-derive an exported Milexium evidence pack.

    py -3 -m demo.verify_pack artifacts/demo-walkthrough

This is the third party's side of the walkthrough, and it is deliberately thin:
it reads one JSON file off disk, hands it to `packages.evidence.
verify_evidence_pack`, and prints what came back. It computes no figure of its
own -- if it did, a reader would have to trust this module too.

What that one call re-derives, none of it from a manifest claim:

  * the bundle checksum, recomputed over the embedded body;
  * the append-only hash chain, recomputed from the raw ledger rows the pack
    carries (not from the reconstructed narrative);
  * every manifest claim, recomputed from the body it summarises -- the bundle
    hash deliberately excludes the manifest, so a manifest describing a
    different pack is caught here and nowhere else;
  * the narrative, checked field by field against those same raw rows;
  * the carried deadhead teardown: totals, hour and day buckets, run
    attribution, the reconciliation and the cost arithmetic, all recomputed
    from the embedded segments and the manifest's DECLARED inputs, plus the
    segment fingerprint that binds the figures to those segments.

`packages/evidence/teardown_evidence.py` (the re-derivation) does not import
`packages/replay/teardown.py` (the generator), so agreement is not the generator
agreeing with itself.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from packages.evidence import EvidencePack, verify_evidence_pack

PACK_NAME = "evidence_pack.json"


def verify_pack_file(pack_path: Path, *, say=print) -> dict:
    """Re-derive one pack from its own bytes and report. Returns the
    machine-readable result the walkthrough and its conformance test assert on."""

    pack = EvidencePack.from_json(Path(pack_path).read_text(encoding="utf-8"))
    verification = verify_evidence_pack(pack)

    say(f"[{Path(pack_path).name}]  {Path(pack_path).stat().st_size:,} bytes read from disk")
    say(f"  bundle checksum recomputed over the body    : {verification.bundle_hash_matches}")
    say(f"  hash chain recomputed from the raw rows     : {verification.chain_reverified}")
    say(f"  every manifest claim recomputed from body   : {verification.manifest_consistent}")
    say(f"  narrative checked against the raw rows      : {verification.narrative_consistent}")
    say(f"  teardown carried                            : {verification.teardown_present}")
    say(f"  teardown figures recomputed from segments   : "
        f"{verification.teardown_figures_rederived}")
    say(f"  teardown segment fingerprint recomputed     : "
        f"{verification.teardown_fingerprint_rederived}")
    say(f"  chain violations                            : {len(verification.chain_violations)}")
    say(f"  teardown mismatches                         : "
        f"{len(verification.teardown_mismatches)}")
    say(f"  VERDICT reverified                          : {verification.reverified}")
    for reason in verification.reasons:
        say(f"    ! {reason}")

    teardown = pack.teardown
    checks = 0
    if teardown is not None:
        # The count of quantities the verifier actually recomputed. Reported
        # because "no mismatches" is worthless without knowing how many things
        # were checked -- a verifier that checks nothing also finds nothing.
        from packages.evidence import rederive_teardown

        rederivation = rederive_teardown(teardown)
        checks = len(rederivation.checked)
        say(f"  quantities recomputed, not merely read      : {checks}")
        for name in rederivation.checked[:6]:
            say(f"      {name}")
        say(f"      ... and {max(0, checks - 6)} more")
        say(f"  claimed empty minutes                       : "
            f"{teardown.figures.total_deadhead_minutes}")
        say(f"  claimed value at full cost                  : "
            f"{teardown.figures.value_at_full_cost}")
        say(f"  presented as a guaranteed saving            : False (the model refuses)")

    return {
        "reverified": verification.reverified,
        "bundle_hash_matches": verification.bundle_hash_matches,
        "chain_reverified": verification.chain_reverified,
        "manifest_consistent": verification.manifest_consistent,
        "narrative_consistent": verification.narrative_consistent,
        "teardown_present": verification.teardown_present,
        "teardown_figures_rederived": verification.teardown_figures_rederived,
        "teardown_fingerprint_rederived": verification.teardown_fingerprint_rederived,
        "teardown_checks": checks,
        "teardown_mismatches": tuple(verification.teardown_mismatches),
        "chain_violations": tuple(verification.chain_violations),
        "reasons": tuple(verification.reasons),
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    target = Path(argv[0]) if argv else Path("artifacts/demo-walkthrough")
    pack_path = target if target.is_file() else target / PACK_NAME
    if not pack_path.exists():
        print(f"[stop] not found: {pack_path}")
        print("Run `py -3 -m demo` first, or pass the pack (or the directory holding it).")
        return 1

    result = verify_pack_file(pack_path)
    print("")
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    print("")
    print("RE-DERIVED" if result["reverified"] else "FAILED TO RE-DERIVE")
    return 0 if result["reverified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
