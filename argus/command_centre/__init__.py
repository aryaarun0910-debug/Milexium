"""The Milexium command centre: the operational picture, as one HTML file.

    py -3 -m argus.command_centre

Writes `aletheia/artifacts/command-centre/index.html` and, beside it,
`operating_picture.json` -- the structured record of every figure on the page
with its attribution. The page opens from disk with no web server, no build
step, no CDN and no JavaScript.

WHY IT EXISTS. `py -3 -m argus.demo` is the same chain in a terminal, and it is
excellent and unshowable: the platform's rigour is invisible to anyone who does
not read code. This renders the same synthetic scenario as an operating picture
-- current state, where accessible capacity binds, the decision with every
rejected alternative and its exact binding constraint, what the commitment costs
in future capacity, the human authorisation, and the outcome against what was
expected.

THE PROHIBITION IS THE DESIGN. Argus must never invent a fact, constraint,
reason or recommendation; it renders authority and does not manufacture it. So
nothing reaches the page except as an `attribution.Figure`, which cannot be
constructed without naming the layer, the call and the file its value came from
-- and the renderer prints that attribution under every number rather than
hiding it behind a tooltip. Where a layer declines to produce something, the
page shows the refusal: there is no fallback estimate anywhere in this package.

STATUS. The scenario is synthetic and the page says so in its own banner.
Demonstrated at most; nothing here is Validated. Milexium has zero customers,
zero pilots and zero operator data.

The package deliberately does not eagerly import `picture` (which pulls in the
solver stack) at package-import time, so `py -3 -m argus.command_centre` is free
of the "module already in sys.modules" runtime warning. Import the entry points
from the submodules:

    from argus.command_centre.picture import build_operating_picture
    from argus.command_centre.render import render_html, write_artifact
"""
