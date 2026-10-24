"""Build the HospitalOS logo kit (web/public/brand) from geometry and the outlined wordmark.

    pip install fonttools brotli uharfbuzz   # once
    python web/dev/build_brand.py web/public/brand a

Symbol: two 48x192 stems (radius 8) and a 64 magnet lifted 16 above centre, on a 256 grid.
Wordmark: Atkinson Hyperlegible Next 700 (SIL OFL 1.1), outlined, tracking -1.2 %.
"""

import pathlib
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from wordmark import outline

OUT = pathlib.Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
ARDOISE, VERT, EMAIL, VERT_CLAIR, BLANC = "#15201D", "#1B6A55", "#EDF0EE", "#57B898", "#FFFFFF"

STEMS = (
    "M48 32h32a8 8 0 0 1 8 8v176a8 8 0 0 1-8 8H48a8 8 0 0 1-8-8V40a8 8 0 0 1 8-8Z "
    "M176 32h32a8 8 0 0 1 8 8v176a8 8 0 0 1-8 8h-32a8 8 0 0 1-8-8V40a8 8 0 0 1 8-8Z"
)
MAGNET = "M104 80h48a8 8 0 0 1 8 8v48a8 8 0 0 1-8 8h-48a8 8 0 0 1-8-8V88a8 8 0 0 1 8-8Z"


def svg(vb, body, title):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" role="img" aria-labelledby="t">'
        f'<title id="t">{title}</title>{body}</svg>\n'
    )


def symbol(stems, magnet, dx=0, dy=0, s=1.0):
    t = f' transform="translate({dx} {dy}) scale({s})"' if (dx or dy or s != 1) else ""
    paths = f'<path fill="{stems}" d="{STEMS}"/><path fill="{magnet}" d="{MAGNET}"/>'
    return f'<g id="symbole"{t}>{paths}</g>'


variant = sys.argv[2] if len(sys.argv) > 2 else "a"  # "b": "OS" in a lighter weight (rejected)
runs = [("HospitalOS", 700)] if variant == "a" else [("Hospital", 700), ("OS", 420)]
CAP = 104
d, w = outline(runs, CAP)
WX, BASE = 256, 180


def wordmark(color, dx=WX, dy=BASE):
    return f'<g id="logotype"><path fill="{color}" transform="translate({dx} {dy})" d="{d}"/></g>'


W = round(WX + w + 16)
d2, w2 = outline(runs, 76)
schemes = {
    "couleur": (ARDOISE, VERT, ARDOISE),
    "inverse": (EMAIL, VERT_CLAIR, EMAIL),
    "noir": ("#000000", "#000000", "#000000"),
    "blanc": (BLANC, BLANC, BLANC),
}
files = {}
for name, (st, mg, wm) in schemes.items():
    files[f"hospitalos-symbole-{name}.svg"] = svg("0 0 256 256", symbol(st, mg), "HospitalOS")
    files[f"hospitalos-horizontal-{name}.svg"] = svg(
        f"0 0 {W} 256", symbol(st, mg) + wordmark(wm), "HospitalOS"
    )
    files[f"hospitalos-logotype-{name}.svg"] = svg(
        f"0 0 {round(w + 16)} 136", wordmark(wm, 8, 120), "HospitalOS"
    )
    # stacked: symbol 256 on top, wordmark centered below
    SW = max(256, round(w2 + 32))
    sx = (SW - 256) / 2
    files[f"hospitalos-vertical-{name}.svg"] = svg(
        f"0 0 {SW} 360",
        symbol(st, mg, dx=sx)
        + f'<g id="logotype"><path fill="{wm}" '
        + f'transform="translate({(SW - w2) / 2} {324})" d="{d2}"/></g>',
        "HospitalOS",
    )
# app icon & favicon: symbol at 62 % inside a rounded tile
files["hospitalos-icone-app.svg"] = svg(
    "0 0 256 256",
    f'<rect width="256" height="256" rx="56" fill="{ARDOISE}"/>'
    + symbol(EMAIL, VERT_CLAIR, dx=48.6, dy=48.6, s=0.62),
    "HospitalOS",
)
files["hospitalos-favicon.svg"] = svg(
    "0 0 256 256",
    f'<rect width="256" height="256" rx="48" fill="{ARDOISE}"/>'
    + symbol(EMAIL, VERT_CLAIR, dx=28.2, dy=28.2, s=0.78),
    "HospitalOS",
)
for n, c in files.items():
    (OUT / n).write_text(c)
print(len(files), "files", W)
