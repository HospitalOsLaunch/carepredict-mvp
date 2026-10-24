"""Outline the HospitalOS wordmark from Atkinson Hyperlegible Next (SIL OFL 1.1)."""

import io

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

FONT_DIR = "node_modules/@fontsource-variable/atkinson-hyperlegible-next/files"
SRC = str(
    __import__("pathlib").Path(__file__).resolve().parents[1]
    / FONT_DIR
    / "atkinson-hyperlegible-next-latin-wght-normal.woff2"
)


LEXEND = str(
    __import__("pathlib").Path(__file__).resolve().parents[1]
    / "node_modules/@fontsource-variable/lexend/files"
    / "lexend-latin-wght-normal.woff2"
)


def instance(weight, src=SRC):
    f = TTFont(src)
    inst = instantiateVariableFont(f, {"wght": weight})
    buf = io.BytesIO()
    inst.flavor = None
    inst.save(buf)
    return inst, buf.getvalue()


def outline(runs, cap_px, tracking_em=-0.012, src=SRC):
    """runs: [(text, weight)]. Returns (path_d, width_px) with baseline at y=0, y down."""
    d_parts = []
    x = 0.0
    for text, weight in runs:
        font, data = instance(weight, src)
        upem = font["head"].unitsPerEm
        scale = cap_px / font["OS/2"].sCapHeight
        face = hb.Face(data)
        hfont = hb.Font(face)
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(hfont, buf, {"kern": True, "liga": False})
        gs = font.getGlyphSet()
        order = font.getGlyphOrder()
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions, strict=True):
            name = order[info.codepoint]
            pen = SVGPathPen(gs)
            tpen = TransformPen(
                pen, (scale, 0, 0, -scale, x + pos.x_offset * scale, -pos.y_offset * scale)
            )
            gs[name].draw(tpen)
            d_parts.append(pen.getCommands())
            x += pos.x_advance * scale + tracking_em * upem * scale
    return " ".join(d_parts), x - tracking_em * 1000 * (cap_px / 668)


if __name__ == "__main__":
    d, w = outline([("HospitalOS", 700)], 100)
    print(round(w, 1), len(d))
