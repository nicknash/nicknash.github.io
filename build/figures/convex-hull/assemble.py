"""Package two full-width section figures, sharing the video and area scales."""
import html
import json
import re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
DEST = HERE.parents[2] / "assets/convex-hull"
data = json.loads((DEST / "filled-area.json").read_text())
video_layout = json.loads((DEST / "video-layout.json").read_text())
template = (HERE / "figure.html").read_text()
panels = re.findall(r"    <figure>.*?    </figure>", template, re.S)
assert len(panels) == len(data["series"]) == 5
variants = [
    dict(slug="convex-hull-slow", tiles=[0, 1], arrow=False,
         title="Humans only and AI ruins serendipity",
         description="Humans only alongside AI ruins serendipity: AI fills existing gaps, but new human discoveries become less frequent."),
    dict(slug="convex-hull", tiles=[2, 3, 4], arrow=True,
         title="Knowledge with stronger feedback",
         description="Three illustrative paths with increasing feedback: weak feedback, strong feedback, and autonomous recursive self-improvement."),
]

paper, ink = (253, 252, 249), (48, 49, 46)
font_dir = Path("/usr/share/fonts/truetype/dejavu")
title = ImageFont.truetype(str(font_dir / "DejaVuSans.ttf"), 30)
label = ImageFont.truetype(str(font_dir / "DejaVuSerif.ttf"), 24)
note = ImageFont.truetype(str(font_dir / "DejaVuSerif-Italic.ttf"), 20)
for variant in variants:
    tiles = variant["tiles"]
    output = DEST.parent / variant["slug"]
    output.mkdir(exist_ok=True)
    selected = dict(data, tiles=tiles, video=video_layout, sharedYMax=data["yMax"][0])
    for key in ("names", "series", "rounds", "yMax"):
        selected[key] = [data[key][i] for i in tiles]
    if 1 in tiles:
        selected["names"][tiles.index(1)] = "AI ruins serendipity"
    page = template
    for i, panel in enumerate(panels):
        if i not in tiles:
            page = page.replace(panel, "")
    substitutions = {
        "PANEL_COUNT": str(len(tiles)),
        "FIGURE_TITLE": html.escape(variant["title"]),
        "FIGURE_DESCRIPTION": html.escape(variant["description"]),
        "FEEDBACK_DIRECTION": (
            '<div class="feedback-direction"><p>Stronger feedback</p>'
            '<div class="feedback-arrow" aria-hidden="true"></div></div>'
            if variant["arrow"] else ""),
        "AREA_DATA": json.dumps(selected, separators=(",", ":")),
    }
    for key, value in substitutions.items():
        page = page.replace("{{" + key + "}}", value)
    page = page.replace('src="circle-', 'src="../convex-hull/circle-')
    page = page.replace("shared by the first four plots", "shared across both figures")
    assert not re.search(r"\{\{[A-Z_]+\}\}", page)
    (output / "index.html").write_text(
        "\n".join(line.rstrip() for line in page.splitlines()) + "\n")

    # Spread columns across the page, but keep the shapes at a shared scale.
    offset = 0 if variant["arrow"] else -70
    column_width = (1100 - 40 - 24 * (len(tiles) - 1)) // len(tiles)
    tile_width = (1100 - 40 - 24 * 2) // 3
    tile_height = round(tile_width * 438 / 516)
    visual_top = 120 + offset
    chart_top = visual_top + tile_height + 10
    chart_bottom = chart_top + 208
    image = Image.new("RGB", (1100, chart_bottom + 20), paper)
    draw = ImageDraw.Draw(image)
    if variant["arrow"]:
        draw.text((550, 15), "Stronger feedback", fill=ink, font=title, anchor="mt")
        draw.line((20, 62, 1078, 62), fill=ink, width=3)
        draw.line((1066, 52, 1078, 62, 1066, 72), fill=ink, width=3)
    for position, i in enumerate(tiles):
        values = data["series"][i]
        x = 20 + position * (column_width + 24)
        if i in (0, 1):
            draw.text((x + column_width / 2, 86 + offset),
                      "Humans only" if i == 0 else "AI ruins serendipity",
                      fill=ink, font=label, anchor="mt")
        poster = Image.open(DEST / f"circle-{i}.webp").convert("RGB")
        visual_x = x + (column_width - tile_width) // 2
        image.paste(poster.resize((tile_width, tile_height), Image.Resampling.LANCZOS), (visual_x, visual_top))
        if i == 4:
            draw.text((x+4, chart_top), "10× vertical range", fill=(90, 91, 85), font=note)
        points = [(x+4+(column_width-8)*n/(len(values)-1), chart_bottom-180*v/data["yMax"][i])
                  for n, v in enumerate(values)]
        draw.line(points, fill=ink, width=3)
        end_x, end_y = points[-1]
        draw.ellipse((end_x-4, end_y-4, end_x+4, end_y+4), fill=ink)
    image.save(output / "poster.png", optimize=True)
    print(f"Assembled {len(tiles)}-panel HTML and print figure: {variant['slug']}")
