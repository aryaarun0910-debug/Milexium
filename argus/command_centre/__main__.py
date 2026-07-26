"""`py -3 -m argus.command_centre` builds the operating picture and writes it."""

from __future__ import annotations

import argparse
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    from argus.command_centre.picture import DEFAULT_OUTPUT_DIR, build_operating_picture
    from argus.command_centre.render import write_artifact

    parser = argparse.ArgumentParser(
        prog="argus.command_centre",
        description=(
            "Build the Milexium operating picture as one self-contained HTML file. "
            "Synthetic scenario; Demonstrated, not Validated."
        ),
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        default=None,
        help=f"where to write the artifact (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--skip-real-drift",
        action="store_true",
        help=(
            "omit the serve-time drift section, which reads a 571k-row committed panel "
            "and is the single most expensive thing on the page. The section is REMOVED, "
            "not replaced, and the page records that it is missing."
        ),
    )
    args = parser.parse_args(argv)

    picture = build_operating_picture(include_real_drift=not args.skip_real_drift)
    page, sidecar = write_artifact(
        picture, Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR
    )

    print(f"operating picture written in {picture.runtime_seconds:.1f} s")
    print(f"  page     {page}")
    print(f"  data     {sidecar}")
    print(f"  figures  {len(picture.ledger)} ({picture.ledger.by_origin()})")
    print(f"  refusals {len(picture.refusals)}")
    print("Demonstrated. Not Validated. No customers, no pilots, no operator data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
