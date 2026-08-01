#!/usr/bin/env python3
"""Replace a donor atlas's leader portraits and insignia with our own art.

<faction>.pcx is the faction sprite atlas (see factions/README.md). A new
faction inherits a stock atlas so its bases and colours work, but that also
inherits the donor's FACE -- Kaya wearing Deirdre's portrait on every council
and diplomacy screen.

The atlas labels its own regions in the image ("SMALL COUNCIL", "BIG COUNCIL",
"DIPLOMACY", "COUNCIL LOGOS", "DIPLOMACY LOGO"), and the layout is identical
across all fourteen shipped factions, so the boxes are found rather than
hardcoded: within a column window, a portrait row is almost entirely non-key
pixels while a caption row is mostly magenta, so thresholding row density
separates the artwork from the label beneath it.

Only those regions are touched. Base sprites, unit sprites and the colour
swatches -- the parts that made the bases visible again -- are left exactly as
the donor drew them.

    ./repaint_atlas.py suffic.pcx --art suffic3.pcx
    ./repaint_atlas.py suffic.pcx --art suffic3.pcx --preview /tmp/p.png
"""
import argparse
import os
import sys

try:
    from PIL import Image
except ImportError:
    sys.exit("needs Pillow")

KEY = (255, 0, 255)      # magenta transparency key
LABEL = {(0, 255, 255), (0, 255, 0)}   # caption colours, not artwork

# Column windows for each region. Rows are measured, not assumed.
#
# The faces are rectangular photographs and can simply be pasted over. The
# insignia are DIAMONDS whose corners are transparency key, so a rectangular
# paste would fill those corners in and break the shape -- they are opt-in and
# want art cut to the diamond, not a crop.
FACE_WINDOWS = {
    "small_council": (80, 189),
    "big_council":   (191, 293),
    "diplomacy":     (295, 431),
}
LOGO_WINDOWS = {
    "council_logos": (0, 75),
    "diplo_logo":    (432, 505),
}
BAND = (450, 640)        # the portrait band, below the base-sprite rows


def row_boxes(im, x0, x1, y0, y1, min_fill=0.55):
    """Contiguous row runs where the window is mostly real artwork."""
    px = im.convert("RGB").load()
    w = x1 - x0
    rows = []
    for y in range(y0, y1):
        n = 0
        for x in range(x0, x1):
            p = px[x, y]
            if p != KEY and p not in LABEL:
                n += 1
        rows.append(n / w >= min_fill)

    runs, start = [], None
    for i, on in enumerate(list(rows) + [False]):
        if on and start is None:
            start = i
        elif not on and start is not None:
            if i - start >= 20:
                runs.append((y0 + start, y0 + i))
            start = None
    return runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("atlas", help="the faction's .pcx atlas, edited in place")
    ap.add_argument("--art", required=True,
                    help="image to place in the portrait/insignia regions")
    ap.add_argument("--preview", help="also write a PNG of the result")
    ap.add_argument("--logos", action="store_true",
                    help="also repaint the diamond insignia (rectangular "
                         "paste fills their transparent corners)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    im = Image.open(args.atlas)
    rgb = im.convert("RGB")
    art = Image.open(args.art).convert("RGB")

    windows = dict(FACE_WINDOWS)
    if args.logos:
        windows.update(LOGO_WINDOWS)

    regions = []
    for name, (x0, x1) in windows.items():
        runs = row_boxes(rgb, x0, x1, *BAND)
        if not runs:
            print(f"  {name}: no artwork found, skipping", file=sys.stderr)
            continue
        for (y0, y1) in runs:
            regions.append((name, x0, y0, x1, y1))
            print(f"  {name:15} ({x0},{y0})-({x1},{y1})  {x1-x0}x{y1-y0}")

    if args.dry_run:
        return 0

    # Paste in PALETTE space, never through RGB. Converting the whole atlas to
    # RGB and quantising it back re-picked indices for pixels outside the
    # regions -- the base sprites came out different from the donor's, which is
    # the same class of bug that made the bases invisible to begin with. Only
    # the pasted rectangles may change.
    for name, x0, y0, x1, y1 in regions:
        w, h = x1 - x0, y1 - y0
        sw, sh = art.size
        s = max(w / sw, h / sh)   # cover-crop; never squash to the region aspect
        tile = art.resize((max(1, round(sw * s)), max(1, round(sh * s))),
                          Image.LANCZOS)
        left = (tile.width - w) // 2
        top = (tile.height - h) // 2
        tile = tile.crop((left, top, left + w, top + h))
        im.paste(tile.quantize(palette=im, dither=Image.NONE), (x0, y0))

    im.save(args.atlas, format="PCX")
    print(f"  repainted {len(regions)} regions in {os.path.basename(args.atlas)}")

    if args.preview:
        Image.open(args.atlas).convert("RGB").save(args.preview)
    return 0


if __name__ == "__main__":
    sys.exit(main())
