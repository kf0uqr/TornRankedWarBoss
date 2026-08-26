"""Renders tables to PNG images for the Discord bot, matching the web app's
dark theme "Copy as Image" feature (frontend/app.js's copyTablesAsImage) -
the two are separate implementations (Python has no canvas), so keep them
visually in sync by hand if one changes.
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

COLORS = {
    "panel": (27, 30, 39),
    "panel_alt": (35, 39, 53),
    "stripe": (34, 37, 45),  # panel blended with ~3% white, for alternating rows
    "border": (46, 51, 66),
    "text": (230, 232, 238),
    "text_dim": (154, 161, 178),
    "accent": (93, 169, 255),
    "bad": (224, 97, 107),
}

_REGULAR_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:\\Windows\\Fonts\\arial.ttf",
]
_BOLD_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:\\Windows\\Fonts\\arialbd.ttf",
]

_font_cache: dict[tuple[bool, int], ImageFont.FreeTypeFont] = {}


def _load_font(bold: bool, size: int):
    key = (bold, size)
    if key in _font_cache:
        return _font_cache[key]
    for path in _BOLD_FONT_PATHS if bold else _REGULAR_FONT_PATHS:
        try:
            font = ImageFont.truetype(path, size)
            break
        except OSError:
            continue
    else:
        font = ImageFont.load_default()
    _font_cache[key] = font
    return font


CELL_FONT_SIZE = 15
HEADER_FONT_SIZE = 15
TITLE_FONT_SIZE = 22
SUBHEADER_FONT_SIZE = 17
COL_PAD = 14
ROW_HEIGHT = 30
PADDING = 24
TITLE_HEIGHT = 36
SECTION_GAP = 22
SUBHEADER_HEIGHT = 26


def _cell_text(cell) -> str:
    return cell["text"] if isinstance(cell, dict) else str(cell)


def _cell_color(cell):
    if isinstance(cell, dict) and cell.get("color"):
        return cell["color"]
    return COLORS["text"]


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    if not text:
        return 0
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def render_tables(title: str, sections: list[dict]) -> bytes:
    """sections: [{"heading": str | None, "headers": [str, ...], "rows": [[cell, ...], ...]}]
    A cell is a plain value or {"text": str, "color": (r,g,b)}. Returns PNG bytes."""
    header_font = _load_font(True, HEADER_FONT_SIZE)
    cell_font = _load_font(False, CELL_FONT_SIZE)
    title_font = _load_font(True, TITLE_FONT_SIZE)
    subheader_font = _load_font(True, SUBHEADER_FONT_SIZE)

    measure_img = Image.new("RGB", (1, 1))
    mdraw = ImageDraw.Draw(measure_img)

    # Sections sharing identical headers get matching column widths, same as
    # the web app's version, so tables line up (e.g. Leadership/Everyone Else).
    groups: dict[tuple, list[int]] = {}
    for i, section in enumerate(sections):
        groups.setdefault(tuple(section["headers"]), []).append(i)

    col_widths_by_section: list[list[int]] = [[] for _ in sections]
    for headers, idxs in groups.items():
        widths = [_text_width(mdraw, h, header_font) for h in headers]
        for i in idxs:
            for row in sections[i]["rows"]:
                for ci, cell in enumerate(row):
                    widths[ci] = max(widths[ci], _text_width(mdraw, _cell_text(cell), cell_font))
        for i in idxs:
            col_widths_by_section[i] = widths

    width = max(
        sum(w + COL_PAD * 2 for w in col_widths_by_section[i]) for i in range(len(sections))
    ) + PADDING * 2

    height = PADDING * 2 + TITLE_HEIGHT
    for i, section in enumerate(sections):
        if section.get("heading"):
            height += SUBHEADER_HEIGHT
        height += ROW_HEIGHT * (len(section["rows"]) + 1)
        if i < len(sections) - 1:
            height += SECTION_GAP

    img = Image.new("RGB", (width, height), COLORS["panel"])
    draw = ImageDraw.Draw(img)

    y = PADDING
    draw.text((PADDING, y), title, font=title_font, fill=COLORS["text"])
    y += TITLE_HEIGHT

    for i, section in enumerate(sections):
        if section.get("heading"):
            draw.text((PADDING, y), section["heading"], font=subheader_font, fill=COLORS["accent"])
            y += SUBHEADER_HEIGHT

        col_widths = col_widths_by_section[i]
        total_w = sum(w + COL_PAD * 2 for w in col_widths)

        draw.rectangle([PADDING, y, PADDING + total_w, y + ROW_HEIGHT], fill=COLORS["panel_alt"])
        x = PADDING
        for header, w in zip(section["headers"], col_widths):
            draw.text((x + COL_PAD, y + ROW_HEIGHT / 2), header, font=header_font, fill=COLORS["text_dim"], anchor="lm")
            x += w + COL_PAD * 2

        row_y = y + ROW_HEIGHT
        for ri, row in enumerate(section["rows"]):
            if ri % 2 == 1:
                draw.rectangle([PADDING, row_y, PADDING + total_w, row_y + ROW_HEIGHT], fill=COLORS["stripe"])
            x = PADDING
            for cell, w in zip(row, col_widths):
                draw.text(
                    (x + COL_PAD, row_y + ROW_HEIGHT / 2),
                    _cell_text(cell),
                    font=cell_font,
                    fill=_cell_color(cell),
                    anchor="lm",
                )
                x += w + COL_PAD * 2
            row_y += ROW_HEIGHT

        draw.rectangle([PADDING, y, PADDING + total_w, row_y], outline=COLORS["border"], width=1)
        y = row_y
        if i < len(sections) - 1:
            y += SECTION_GAP

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
