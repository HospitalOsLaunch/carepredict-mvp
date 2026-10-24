"""Build the HospitalOS logo kit (web/public/brand) from geometry and the outlined wordmark.

    pip install fonttools brotli uharfbuzz   # once
    python web/dev/build_brand.py web/public/brand

Symbol « Lumière » on a 256 grid: two beds as 52x192 pills, and between them a sun
(r 30) rising 20 above centre: the place that frees up lets the light in.
Wordmark: Lexend 600 (SIL OFL 1.1), outlined, tracking -2 %.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from wordmark import LEXEND, outline

OUT = pathlib.Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)

OUTREMER, SOLEIL, NUIT, AIR, BLANC = "#3047E6", "#FFB61A", "#121A3A", "#F4F7FF", "#FFFFFF"
SOLEIL_NUIT = "#FFC94D"

BEDS = (
    "M62 32a26 26 0 0 1 26 26v140a26 26 0 0 1-52 0V58a26 26 0 0 1 26-26Z "
    "M194 32a26 26 0 0 1 26 26v140a26 26 0 0 1-52 0V58a26 26 0 0 1 26-26Z"
)
SUN = "M128 78a30 30 0 1 1 0 60a30 30 0 1 1 0-60Z"


def svg(vb, body, title="HospitalOS"):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" role="img" aria-labelledby="t">'
        f'<title id="t">{title}</title>{body}</svg>\n'
    )


def symbol(beds, sun, dx=0.0, dy=0.0, s=1.0):
    t = f' transform="translate({dx} {dy}) scale({s})"' if (dx or dy or s != 1) else ""
    return f'<g id="symbole"{t}><path fill="{beds}" d="{BEDS}"/><path fill="{sun}" d="{SUN}"/></g>'


RUNS = [("HospitalOS", 600)]
d, w = outline(RUNS, 100, tracking_em=-0.02, src=LEXEND)
d2, w2 = outline(RUNS, 74, tracking_em=-0.02, src=LEXEND)
WX, BASE = 252, 178


def wordmark(color, path=d, dx=WX, dy=BASE):
    return (
        f'<g id="logotype"><path fill="{color}" transform="translate({dx} {dy})" d="{path}"/></g>'
    )


W = round(WX + w + 16)
SW = max(256, round(w2 + 32))
schemes = {
    # name: (beds, sun, wordmark) — "couleur" on light grounds, "inverse" on outremer,
    # "nuit" on night blue, "noir" / "blanc" for one-ink uses.
    "couleur": (OUTREMER, SOLEIL, NUIT),
    "inverse": (BLANC, SOLEIL, BLANC),
    "nuit": (AIR, SOLEIL_NUIT, AIR),
    "noir": ("#000000", "#000000", "#000000"),
    "blanc": (BLANC, BLANC, BLANC),
}
files = {}
for name, (beds, sun, ink) in schemes.items():
    files[f"hospitalos-symbole-{name}.svg"] = svg("0 0 256 256", symbol(beds, sun))
    files[f"hospitalos-horizontal-{name}.svg"] = svg(
        f"0 0 {W} 256", symbol(beds, sun) + wordmark(ink)
    )
    files[f"hospitalos-logotype-{name}.svg"] = svg(
        f"0 0 {round(w + 16)} 136", wordmark(ink, d, 8, 118)
    )
    files[f"hospitalos-vertical-{name}.svg"] = svg(
        f"0 0 {SW} 360",
        symbol(beds, sun, dx=(SW - 256) / 2) + wordmark(ink, d2, (SW - w2) / 2, 326),
    )
files["hospitalos-icone-app.svg"] = svg(
    "0 0 256 256",
    f'<rect width="256" height="256" rx="56" fill="{OUTREMER}"/>'
    + symbol(BLANC, SOLEIL, dx=48.6, dy=52.6, s=0.62),
)
files["hospitalos-favicon.svg"] = svg(
    "0 0 256 256",
    f'<rect width="256" height="256" rx="48" fill="{OUTREMER}"/>'
    + symbol(BLANC, SOLEIL, dx=28.2, dy=32.2, s=0.78),
)
for old in OUT.glob("hospitalos-*.svg"):
    old.unlink()
for n, c in files.items():
    (OUT / n).write_text(c)
print(len(files), "files", W)
