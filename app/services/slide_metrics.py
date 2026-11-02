"""Measured text capacity for the deterministic slide distributor."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

RES_DIR = Path(__file__).parent.parent / "res"


def _font(name: str, size: int):
    return ImageFont.truetype(str(RES_DIR / name), size=size)


def _line_height(font, spacing: int = 0) -> int:
    ascent, descent = font.getmetrics()
    return ascent + descent + spacing


def _wrap_count(draw, text: str, font, max_width: int) -> int:
    lines = 1
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines += 1
            current = word
    return lines


def _capacity(
    headline: str,
    *,
    headline_size: int,
    body_size: int,
    headline_width: int,
    body_width: int,
    headline_top: int,
    body_gap: int,
    body_max_y: int,
    headline_spacing: int,
    body_spacing: int,
    safety: float = 0.82,
) -> int:
    draw = ImageDraw.Draw(Image.new("RGB", (1080, 1920)))
    headline_font = _font("Oswald-Bold.ttf", headline_size)
    body_font = _font("Inter-Regular.ttf", body_size)
    headline_lines = _wrap_count(draw, headline, headline_font, headline_width)
    body_top = (
        headline_top
        + headline_lines * _line_height(headline_font, headline_spacing)
        + body_gap
    )
    body_height = max(1, body_max_y - body_top)
    sample = "abcdefghijklmnopqrstuvwxyz"
    avg_char = max(1.0, draw.textlength(sample, font=body_font) / len(sample))
    chars_per_line = max(1, int(body_width / avg_char))
    body_lines = max(1, int(body_height / _line_height(body_font, body_spacing)))
    return max(180, int(chars_per_line * body_lines * safety))


def summary_body_capacity(headline: str) -> int:
    return _capacity(
        headline,
        headline_size=62,
        body_size=34,
        headline_width=880,
        body_width=920,
        headline_top=482,
        body_gap=36,
        body_max_y=1640,
        headline_spacing=6,
        body_spacing=4,
        safety=0.9,
    )


def topic_body_capacity(headline: str) -> int:
    return _capacity(
        headline,
        headline_size=46,
        body_size=32,
        headline_width=460,
        body_width=460,
        headline_top=255,
        body_gap=18,
        body_max_y=1200,
        headline_spacing=-2,
        body_spacing=2,
    )
