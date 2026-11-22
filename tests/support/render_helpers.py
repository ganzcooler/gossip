"""Shared Pillow helpers for the renderer tests."""

from PIL import Image, ImageChops, ImageDraw

from app.services import render_common

LOGO_COLOR = (255, 0, 255)


def use_transparent_logo(monkeypatch, tmp_path) -> None:
    """Use a synthetic ring logo so the real asset can be replaced later."""
    logo = Image.new("RGBA", (100, 50), (0, 0, 0, 0))
    ImageDraw.Draw(logo).rectangle(
        (0, 0, 99, 49), outline=(*LOGO_COLOR, 255), width=10
    )
    path = tmp_path / "synthetic-logo.png"
    logo.save(path)
    monkeypatch.setattr(render_common, "LOGO_PATH", path)


def use_empty_logo(monkeypatch, tmp_path) -> None:
    path = tmp_path / "empty-logo.png"
    Image.new("RGBA", (100, 50), (0, 0, 0, 0)).save(path)
    monkeypatch.setattr(render_common, "LOGO_PATH", path)


def color_bbox(image: Image.Image, box, color) -> tuple[int, int, int, int] | None:
    """Return the exact-color bbox inside ``box``, in image coordinates."""
    region = image.crop(box)
    difference = ImageChops.difference(
        region, Image.new("RGB", region.size, color)
    )
    red, green, blue = difference.split()
    total = ImageChops.add(ImageChops.add(red, green), blue)
    mask = total.point(lambda value: 255 if value == 0 else 0)
    bbox = mask.getbbox()
    if bbox is None:
        return None
    return (
        box[0] + bbox[0],
        box[1] + bbox[1],
        box[0] + bbox[2],
        box[1] + bbox[3],
    )
