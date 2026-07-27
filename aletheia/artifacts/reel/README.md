# Media artifacts

Everything here is generated. Nothing is hand-edited — if a figure changes,
rebuild rather than patch.

**`recording/` is gitignored** (`.gitignore:115`) — the video files are not in
the repo, only on the machine that built them. The HTML sources and the build
scripts are committed, so any clone can regenerate every video with the commands
at the bottom of this file. If you need a copy of an mp4, rebuild it or ask for
the file directly; do not commit it.

## For the YC application

| file | length | use |
|---|---|---|
| `recording/milexium-demo.mp4` | 1:09 | **the Demo Video slot** |

The whole demo is one terminal session — no title cards, no web footage. The
operating picture, the dispatch board and the denial drill-down are all rendered
as terminal output, so nothing breaks the frame.

```
mlx boot                     rings mount, drivers, pii gate, ring enforcement
milexium why --agency        2.3% reported vs 27% / 37% measured by FTA
milexium ingest              pii gate fires ahead of validation
milexium decide && prove     CP-SAT, then re-derivation in a clean interpreter
milexium board --zone 4      dispatch board, four assigned, one denied
milexium why --request       the denial: every alternative, and what bound
milexium refuse --list       what the platform declines to tell you
milexium system --render     the architecture, held as the closing frame
```

It is built around a **denial**, not a successful assignment: a success shows
nothing an incumbent cannot also show, and the denial closes the loop back to
the Memphis finding that opens the session.

The founder video is a separate recording from the locked script and is not
generated here.

### What is real and what is illustrative

Numbers a reader can check are real and must stay accurate if this is edited:
Memphis 2.3% / 27% / 37% (FTA 2020 review), the Cordeau `a3-18` gap of 0.00%,
28 objects and 23 links, the test count, and the reason codes — those come from
the live `ReasonCode` enum in `themis/canonical/vocab.py`, so what is on screen
matches what a reader finds in the repo.

The trip IDs, vehicle assignments and times are an illustrative scenario, built
to be operationally plausible (dialysis recurring Mon/Wed/Fri, cutaway vans with
two securement positions, one ambulatory-only vehicle, a window breach measured
against the one-hour negotiation rule in 49 CFR §37.131). No operator has run
this. Do not present the scenario as an operator result anywhere it would be
read as one.

## For the website

| file | what it is |
|---|---|
| `system.png` | the architecture still, 1920×716, blue/neon, edge → core → evidence → surface with the agent worker band |
| `recording/milexium-system.mp4` | the same diagram assembling itself, 40s, loops cleanly as a hero background |
| `recording/milexium-reel.mp4` | terminal-style walkthrough of the decision loop, 44s |
| `tty.png` | the terminal frame as a still, 1920×1080 |
| `cards.html` | 1920×1080 title cards — no longer used by the demo, kept for slides |

### Notes for Chris, from rendering the live site

The site's base (`#0d0d0d`, blue accent) is already close to this palette, so
these drop in without a restyle. Three things I noticed that are worth a look —
I did not touch the site:

1. **"Watch one decision unfold"** is the natural slot for
   `recording/milexium-system.mp4` (silent, 40s, loops) or the full
   `milexium-demo.mp4`.
2. **"One living system, three named authorities"** — there are five (Themis,
   Metis, Aletheia, Argus, Talos), and the diagram now also shows the edge and
   agent layers. The count is out of date.
3. **The hero says "forecasts demand with validated ML."** `Validated` is a
   reserved word in ADR-0001 and means a result on consented operator data,
   which we do not have. The strapline three lines below already says
   "Demonstrated on public and synthetic data," so the page currently
   contradicts itself. Suggest "demonstrated" in the hero.

Palette, if anything else needs to match it:

```
bg    #04070f      themis   #00d9ff   (cyan)
panel #070c18      metis    #c76bff   (violet)
box   #0a1122      aletheia #3dffa8   (mint)
line  #152238      argus    #ffb340   (amber)
ink   #dbe6f5      talos    #6c8cff   (indigo)
mut   #6b7f9c      edge     #ff4d8d   (pink)
                   agents   #7dfaff   (ice)
```

## Rebuilding

```
node talos/tools/media/record_tty.mjs         # the demo session, 1:09
bash talos/tools/media/build_demo.sh          # publishes it as milexium-demo.mp4

node talos/tools/media/record_system.mjs      # the graphical diagram, 40s
node talos/tools/media/record_reel.mjs        # the older layer reel, 44s
node talos/tools/media/record_demo.mjs        # the command-centre tour, 1:28
```

Nothing is sped up. `tty.html` paces itself to be read; the spinners and the
progress bar carry the waits.

Open `tty.html?still=1` to render the finished session without the animation —
that is how `tty.png` is produced.

## Source pages

`system.html`, `reel.html`, `cards.html` — self-contained, no external requests.
Open any of them directly in a browser to preview.

## What the diagram claims

The five layers, the loop, and the refusals are built and covered by the test
suite. **The edge silicon path and the agent worker pool are architecture, not
deployed** — the footer and the layer badges say so, and the copy stays in
design tense throughout. ADR-0056 recorded that the measured trigger for a
hardware data plane has not fired; the diagram shows the design without
asserting it runs today.
