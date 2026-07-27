#!/usr/bin/env bash
# Assemble the YC demo cut.
#
# The whole demo is the terminal session. There are no title cards and no
# separate command-centre footage: the operating picture, the dispatch board
# and the denial drill-down are all rendered as terminal output, so nothing
# breaks the frame. `record_tty.mjs` produces the session; this trims the tail
# and publishes it as the demo.
#
# Arc:
#   mlx boot                    rings, drivers, pii gate, ring enforcement
#   milexium why --agency       the FTA finding: 2.3% reported, 27% measured
#   milexium ingest             pii gate fires ahead of validation
#   milexium decide && prove    CP-SAT, then re-derivation in a clean interpreter
#   milexium board              the dispatch board, one trip denied
#   milexium why --request      the denial: every alternative and what bound
#   milexium refuse --list      what the platform declines to tell you
#   milexium system --render    the architecture, held as the closing frame
set -euo pipefail

REPO="c:/Users/aryaa/Documents/Milexium"
REC="$REPO/aletheia/artifacts/reel/recording"
SRC="$REC/milexium-tty.mp4"
OUT="$REC/milexium-demo.mp4"

FF=$(py -3 -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())")

[ -f "$SRC" ] || { echo "missing $SRC — run: node talos/tools/media/record_tty.mjs" >&2; exit 1; }

cp "$SRC" "$OUT"
# ffmpeg -i with no output always exits 1; don't let set -e kill the script here
"$FF" -i "$OUT" 2>&1 | grep -E "Duration|Stream #0:0" || true
echo "demo written: $OUT"
