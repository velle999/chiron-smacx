#!/usr/bin/env python3
"""Build SMACX faction artwork.

The game wants three files per faction, 8-bit indexed PCX:

    <name>.pcx    1024x768   leader portrait
    <name>2.pcx    200x120   small portrait (diplomacy, datalinks)
    <name>3.pcx   1024x768   secondary portrait

The palette is NOT fixed: most shipped files share one 256-colour palette, but
Gaians.pcx and hive.pcx each carry their own and load fine, so the game reads
the palette per file. That means any image can be used -- the work is only
cropping to aspect, quantising to 256 colours, and writing PCX.

Two modes:

  --from IMAGE    palettise a real image (a painting, a render, generated art)
                  into the three files. This is the path to actual artwork.

  (no --from)     generate an emblem card: a flat, deliberate title-card look
                  that is obviously a design choice rather than a bad face.
                  Ships something loadable today.

Usage:
    ./make_art.py suffic
    ./make_art.py oracle --from ~/Downloads/ravn.png
    ./make_art.py suffic --install "$GAME"
"""
import argparse
import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("needs Pillow: pacman -S python-pillow")

# PIL's built-in font is an 8px bitmap and does not scale, which on a 1024px
# canvas renders the wordmark at about the size of a full stop. Any scalable
# face will do; the mono ones suit a faction plate.
FONT_CANDIDATES = [
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    "/usr/share/fonts/TTF/DejaVuSansCondensed.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]


def load_font(px):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, px)
    return ImageFont.load_default()

SIZES = {"": (1024, 768), "2": (200, 120), "3": (1024, 768)}

# Emblem designs. Colours are the faction's argument, not decoration:
# the Sufficiency is warm, low-contrast and level; the Directorate is cold,
# precise and off-balance.
THEMES = {
    "suffic": {
        "name": "KAYA'S SUFFICIENCY",
        "motto": "TAKE ONLY WHAT WE NEED",
        "bg": (26, 22, 16),
        "ink": (214, 186, 130),
        "accent": (140, 158, 96),
        "glyph": "bowl",
    },
    "oracle": {
        "name": "THE CASSANDRA DIRECTORATE",
        "motto": "FOREWARNED, DISBELIEVED",
        "bg": (12, 16, 22),
        "ink": (168, 196, 214),
        "accent": (196, 122, 96),
        "glyph": "forecast",
    },
}


def draw_bowl(d, cx, cy, r, ink, accent):
    """A level vessel: a bowl filled exactly to its rim, not past it."""
    d.arc([cx - r, cy - r, cx + r, cy + r], start=0, end=180, fill=ink, width=max(2, r // 22))
    # the level line -- the whole argument, drawn
    d.line([cx - r, cy, cx + r, cy], fill=accent, width=max(2, r // 26))
    # what is deliberately not taken: dotted continuation above the rim
    step = max(6, r // 12)
    x = cx - r
    while x < cx + r:
        d.line([x, cy - r // 2, x + step // 2, cy - r // 2], fill=ink, width=1)
        x += step
    d.ellipse([cx - r // 14, cy - r // 2 - r // 14, cx + r // 14, cy - r // 2 + r // 14],
              fill=accent)


def draw_forecast(d, cx, cy, r, ink, accent):
    """A confidence interval: a prediction with its error band, and the
    single point where the world went outside it."""
    n = 9
    span = r * 2
    x0 = cx - r
    pts_hi, pts_lo, pts_mid = [], [], []
    vals = [0.10, -0.05, 0.22, 0.05, -0.18, 0.30, 0.12, -0.10, 0.26]
    for i, v in enumerate(vals):
        x = x0 + span * i / (n - 1)
        y = cy - v * r
        band = r * (0.12 + 0.03 * i)
        pts_mid.append((x, y))
        pts_hi.append((x, y - band))
        pts_lo.append((x, y + band))
    d.line(pts_hi, fill=ink, width=1)
    d.line(pts_lo, fill=ink, width=1)
    d.line(pts_mid, fill=ink, width=max(2, r // 40))
    # the observation outside the band: right, and unheeded
    ox, oy = pts_mid[-2][0], pts_lo[-2][1] + r * 0.16
    rr = max(3, r // 26)
    d.ellipse([ox - rr, oy - rr, ox + rr, oy + rr], fill=accent)
    d.line([ox, oy - rr * 3, ox, oy - rr], fill=accent, width=max(1, r // 70))


def emblem(theme, size):
    w, h = size
    im = Image.new("RGB", size, theme["bg"])
    d = ImageDraw.Draw(im)
    small = w < 400

    # hairline frame
    inset = max(3, w // 64)
    d.rectangle([inset, inset, w - inset - 1, h - inset - 1],
                outline=theme["ink"], width=1)

    r = int(min(w, h) * (0.26 if small else 0.22))
    cx, cy = w // 2, int(h * 0.40)
    {"bowl": draw_bowl, "forecast": draw_forecast}[theme["glyph"]](
        d, cx, cy, r, theme["ink"], theme["accent"])

    # wordmark, drawn as a rule + text so it reads as a plate rather than a title
    name_px = max(9, int(h * (0.075 if small else 0.042)))
    motto_px = max(7, int(name_px * 0.55))
    f_name, f_motto = load_font(name_px), load_font(motto_px)

    ty = int(h * 0.68)
    d.line([w * 0.18, ty, w * 0.82, ty], fill=theme["ink"], width=1)

    label = theme["name"]
    if small:  # "SUFFICIENCY" / "DIRECTORATE" -- the noun the game uses
        label = label.replace("'S", " ").split()[-1]
    # letter-spaced, because a faction plate is set wide
    tracking = max(1, name_px // 8)
    widths = [d.textlength(c, font=f_name) for c in label]
    total = sum(widths) + tracking * (len(label) - 1)
    x = (w - total) / 2
    y = ty + max(6, h // 40)
    for c, cw in zip(label, widths):
        d.text((x, y), c, font=f_name, fill=theme["ink"])
        x += cw + tracking

    if not small:
        mw = d.textlength(theme["motto"], font=f_motto)
        d.text(((w - mw) / 2, y + name_px * 1.6), theme["motto"],
               font=f_motto, fill=theme["accent"])
    return im


def to_pcx(im, size, path):
    """Fit to size (cover-crop, never squash), quantise to 256, write PCX."""
    tw, th = size
    sw, sh = im.size
    scale = max(tw / sw, th / sh)
    im = im.resize((max(1, round(sw * scale)), max(1, round(sh * scale))),
                   Image.LANCZOS)
    left = (im.width - tw) // 2
    top = (im.height - th) // 2
    im = im.crop((left, top, left + tw, top + th))
    im = im.convert("RGB").quantize(colors=256, method=Image.MEDIANCUT)
    im.save(path, format="PCX")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("faction", help="file stem, lowercase (suffic, oracle)")
    ap.add_argument("--from", dest="src", help="source image to palettise")
    ap.add_argument("--install", help="also copy into this game directory")
    ap.add_argument("--outdir", default=os.path.dirname(os.path.abspath(__file__)))
    args = ap.parse_args()

    key = args.faction.lower()
    if not args.src and key not in THEMES:
        sys.exit(f"no emblem theme for {key!r}; pass --from IMAGE")

    made = []
    for suffix, size in SIZES.items():
        base = Image.open(args.src) if args.src else emblem(THEMES[key], size)
        name = f"{key}{suffix}.pcx"
        made.append(to_pcx(base, size, os.path.join(args.outdir, name)))

    for p in made:
        im = Image.open(p)
        print(f"  {os.path.basename(p):16} {im.mode}  {im.size}  "
              f"{os.path.getsize(p):>7} B")

    if args.install:
        import shutil
        for p in made:
            shutil.copy2(p, os.path.join(args.install, os.path.basename(p)))
        print(f"installed {len(made)} files into {args.install}")


if __name__ == "__main__":
    main()
