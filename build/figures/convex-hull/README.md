The blog serves two figures: `assets/convex-hull-slow/` for humans only and
“AI ruins serendipity” in Section 1, and `assets/convex-hull/` for weak feedback,
strong feedback and RSI in Section 2. Only the latter has the feedback arrow.
They share the video and individual stills in `assets/convex-hull/`; normal
blog builds do not need the rendering dependencies.

To regenerate, install NumPy, SciPy, Pillow and imageio-ffmpeg in your Python
environment, then run from the repository root:

```sh
python3 build/figures/convex-hull/render.py
python3 build/figures/convex-hull/measure.py
python3 build/figures/convex-hull/assemble.py
```

All five cases share the same initial geometry, fixed camera and four-second
clock, followed by a 0.3-second hold. The video is a five-tile strip, decoded
once per figure and its selected tiles are drawn into two or three canvases.
Paper-coloured gutters separate the tiles in a video aligned to 16-pixel
blocks, preventing the filled RSI crop from bleeding into its neighbour.
`video-layout.json` records the crop positions used by the figure.
Each figure fills the article width, with its two or three panels sharing one
row on desktop and mobile. Shapes are centred inside those panels at the same
pixel scale in both rows, sized from the three-panel row. The area plots keep
their common linear scale.
Plots follow the video's current playback
position, which resets on every loop, rather than decoder frame timestamps.

- Humans only and weak feedback have the same 20 discovery events.
- Slowdown has six events; each interval is 1.65 times the previous interval.
  AI closure stays fast, while new human discoveries become less frequent.
- Strong feedback has 100 human discovery events at an increasing rate, with
  its last infill ending at the plotted endpoint so growth does not flatten.
- RSI has 120 autonomous full-wave discovery/closure cycles. Cycle durations
  decrease with `(1 + 0.033 * round) ** -2`; the final closure ends at the
  plotted endpoint, so the curve keeps rising even after the hull fills its
  visible crop.

These are illustrative schedules, not fitted growth forecasts. One full wave
contains five human discovery lobes. All lobes use the same sine/cosine
profile and fixed radial amplitude; the feedback contrast is in discovery
cadence. The slowdown case reduces new discovery without erasing knowledge.

Area is the union of rendered islands/connections for humans only and the
full geometric convex hull for AI, including outside the crop. During the
initial fade, area interpolates from the known islands to the initial hull.
The first four plots share a linear range of 0–60 initial areas; RSI uses
0–600, marked on the figure. Built-in assertions verify area monotonicity,
discrete discoveries, matched control frontiers and rising strong-feedback
and RSI endpoints.
