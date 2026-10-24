"""App icons (no text, so no font or script issues): a green tile, a sun-yellow disc and a white grain stalk.

    python tools/make_icons.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "web" / "static" / "web" / "icons"


def icon(size, maskable_pad=0.0):
    im = Image.new("RGBA", (size, size), (20, 83, 45, 255))
    d = ImageDraw.Draw(im)
    s = size
    r = s * (0.33 - maskable_pad / 3)
    cx, cy = s / 2, s / 2
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(245, 158, 11, 255))
    # grain stalk: a stem and six grains
    w = max(2, int(s * 0.03))
    d.line([(cx, cy + r * 0.75), (cx, cy - r * 0.7)], fill=(255, 255, 255, 255), width=w)
    for i, dy in enumerate((-0.55, -0.25, 0.05)):
        y = cy + r * dy
        for side in (-1, 1):
            x0 = cx + side * r * 0.08
            x1 = cx + side * r * 0.42
            d.ellipse([min(x0, x1), y - r * 0.12, max(x0, x1), y + r * 0.12], fill=(255, 255, 255, 255))
    return im


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    icon(192).save(OUT / "icon-192.png")
    icon(512, maskable_pad=0.1).save(OUT / "icon-512.png")
    badge = Image.new("RGBA", (72, 72), (0, 0, 0, 0))
    ImageDraw.Draw(badge).ellipse([10, 10, 62, 62], fill=(255, 255, 255, 255))
    badge.save(OUT / "badge-72.png")
    print("icons written")
