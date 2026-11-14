"""Draw the app icon: assets/icon.png (1024), icon.icns (Mac), icon.ico (Windows).

    .venv/bin/python tools/make_icon.py

A stack of three preset cards with a check on the front one: presets, checked. Nothing in
it names the app, so it survives a rename. Deep teal to navy, so it reads in light and dark
Docks; the check is the one warm colour.
"""
import os
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = 1024


def icon() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # background: rounded square, vertical gradient
    grad = Image.new("RGBA", (S, S))
    top, bottom = (22, 120, 128), (18, 34, 74)
    for y in range(S):
        t = y / (S - 1)
        grad.paste(tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,), (0, y, S, y + 1))
    mask = Image.new("L", (S, S), 0)
    m = 100
    ImageDraw.Draw(mask).rounded_rectangle((m, m, S - m, S - m), radius=185, fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    # three cards, back to front
    for i, (shade, dx, dy) in enumerate(((150, 60, -70), (200, 30, -35), (250, 0, 0))):
        x0, y0 = 270 + dx, 330 + dy
        box = (x0, y0, x0 + 430, y0 + 430)
        shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle((box[0] + 10, box[1] + 18, box[2] + 10, box[3] + 18), 48,
                                                 fill=(0, 0, 0, 90))
        img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(16)))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle(box, 48, fill=(shade, shade, shade + 4, 255))
        if i == 2:   # the front card: three knob-and-line rows, like a preset's settings
            for r in range(3):
                cy = y0 + 110 + r * 95
                d.ellipse((x0 + 60, cy - 26, x0 + 112, cy + 26), outline=(40, 60, 90, 255), width=12)
                d.line((x0 + 86, cy, x0 + 86, cy - 22), fill=(40, 60, 90, 255), width=10)
                d.rounded_rectangle((x0 + 145, cy - 10, x0 + 330 - r * 50, cy + 10), 10, fill=(120, 140, 165, 255))
    # the check, on a warm disc, front lower right
    cx, cy, r = 690, 700, 130
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(242, 160, 50, 255), outline=(255, 255, 255, 255), width=16)
    d.line([(cx - 62, cy + 2), (cx - 15, cy + 50), (cx + 66, cy - 48)], fill=(255, 255, 255, 255), width=34,
           joint="curve")
    return img


def main():
    os.makedirs(os.path.join(ROOT, "assets"), exist_ok=True)
    im = icon()
    png = os.path.join(ROOT, "assets", "icon.png")
    im.save(png)
    im.save(os.path.join(ROOT, "assets", "icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                                                             (128, 128), (256, 256)])
    with tempfile.TemporaryDirectory() as t:
        iconset = os.path.join(t, "icon.iconset")
        os.makedirs(iconset)
        for n in (16, 32, 128, 256, 512):
            im.resize((n, n), Image.LANCZOS).save(os.path.join(iconset, f"icon_{n}x{n}.png"))
            im.resize((n * 2, n * 2), Image.LANCZOS).save(os.path.join(iconset, f"icon_{n}x{n}@2x.png"))
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", os.path.join(ROOT, "assets", "icon.icns")], check=True)
    print("icon.png, icon.icns, icon.ico written")


if __name__ == "__main__":
    main()
