"""Erzeugt die App-Symbole (PNG) ohne externe Abhängigkeiten außer Pillow."""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "app" / "icons"
OUT.mkdir(parents=True, exist_ok=True)


def icon(size: int, pad_frac: float, rounded: bool) -> Image.Image:
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bg = (14, 21, 32, 255)
    if rounded:
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=bg)
    else:
        d.rectangle([0, 0, s, s], fill=bg)
    p = s * pad_frac
    w = s - 2 * p
    # Halteband-Zonen als Sockel
    y = p + w * 0.80
    h = w * 0.07
    zones = [(0.0, 0.08, (63, 203, 110, 230)), (0.08, 0.36, (63, 203, 110, 110)),
             (0.36, 0.64, (250, 178, 25, 95)), (0.64, 1.0, (255, 123, 123, 90))]
    for a, b, c in zones:
        al = c[3] / 255
        solid = tuple(int(c[i] * al + bg[i] * (1 - al)) for i in range(3)) + (255,)
        d.rounded_rectangle([p + a * w + 4, y, p + b * w - 4, y + h], radius=int(h / 2), fill=solid)
    # steigende Linie
    pts = [(p + 0.02 * w, p + 0.66 * w), (p + 0.30 * w, p + 0.42 * w), (p + 0.52 * w, p + 0.54 * w), (p + 0.86 * w, p + 0.16 * w)]
    d.line(pts, fill=(125, 183, 255, 255), width=int(w * 0.075), joint="curve")
    r = w * 0.085
    cx, cy = pts[-1]
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(217, 178, 106, 255))
    return img.resize((size, size), Image.LANCZOS)


icon(180, 0.14, False).save(OUT / "apple-touch-icon.png")
icon(192, 0.14, True).save(OUT / "icon-192.png")
icon(512, 0.14, True).save(OUT / "icon-512.png")
icon(512, 0.24, False).save(OUT / "icon-512-maskable.png")
print("Icons erstellt:", sorted(p.name for p in OUT.iterdir()))
