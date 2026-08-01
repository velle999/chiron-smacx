#!/usr/bin/env python3
"""Register faction files in alphax.txt's #CUSTOMFACTIONS block.

This is the mechanism the engine actually provides for adding factions, and
alphax.txt says so itself:

    ; These are factions you want included in the startup list.
    ; These may also be chosen when a random faction is selected.
    #CUSTOMFACTIONS

It is ADDITIVE. #FACTIONS (the original seven) and #NEWFACTIONS (the expansion
seven) stay as they are; anything listed here joins the startup list on top of
them. Nothing has to be displaced to add a faction -- the seven-slot cap is
about how many factions play in one GAME, not how many you can choose among.

Run from install.sh AFTER alphax.txt is copied, because Thinker ships its own
alphax.txt and installing it would otherwise wipe the block. Derives the list
from the faction files present, so adding a faction registers it:

    ./register.py --alphax "$GAME/alphax.txt" --factions ./
    ./register.py --alphax "$GAME/alphax.txt" --factions ./ --check
"""
import argparse
import os
import re
import sys

MARKER = "#CUSTOMFACTIONS"


def faction_stems(d):
    """Stems of faction files in a directory, in stable order."""
    out = []
    for fn in sorted(os.listdir(d)):
        stem, ext = os.path.splitext(fn)
        if ext.lower() != ".txt" or stem.upper() == "FACTION":
            continue
        with open(os.path.join(d, fn), "rb") as fh:
            head = fh.read(2048).decode("cp1252", errors="replace")
        if re.search(r"(?mi)^#" + re.escape(stem.upper()) + r"\s*$", head):
            out.append(stem.upper())
    return out


def rewrite(alphax, stems, check=False):
    with open(alphax, "rb") as fh:
        raw = fh.read()
    text = raw.decode("cp1252", errors="replace")
    nl = "\r\n" if "\r\n" in text else "\n"

    # Stop BEFORE the newline and eat any stray \r, so the rewrite neither
    # inherits nor emits a doubled carriage return. Matching [ \t]*\r?$ here
    # consumed the \r, and body then re-added one: "#CUSTOMFACTIONS\r\r\n",
    # which no longer matched on the next run.
    m = re.search(r"(?m)^" + MARKER + r"[ \t\r]*(?=\n)", text)
    if not m:
        sys.exit(f"no {MARKER} block in {alphax} -- wrong or truncated file")

    # The block runs to the next section header.
    tail = text[m.end():]
    nxt = re.search(r"(?m)^#[A-Z]", tail)
    end = m.end() + (nxt.start() if nxt else len(tail))

    body = nl + nl.join(f"{s},{' ' * max(1, 9 - len(s))}{s}"
                        for s in stems) + nl + nl
    if not stems:
        body = nl + nl

    # Cut at the end of the LITERAL marker, not at m.end(): the trailing
    # [ \t\r]* is matched but slicing to m.end() keeps every character the
    # regex consumed, so the stray carriage returns survived and body added
    # one more on each run. Cutting here drops however many are there.
    new = text[:m.start() + len(MARKER)] + body + text[end:]

    present = re.findall(r"(?m)^([A-Z0-9_]+),\s*[A-Z0-9_]+\s*$",
                         text[m.end():end])
    if check:
        missing = [s for s in stems if s not in present]
        extra = [s for s in present if s not in stems]
        if missing or extra:
            if missing:
                print(f"  NOT registered: {', '.join(missing)}")
            if extra:
                print(f"  stale entries:  {', '.join(extra)}")
            return 1
        print(f"  {MARKER} matches the installed faction files "
              f"({len(stems)}: {', '.join(stems) or 'none'})")
        return 0

    if new == text:
        print(f"  {MARKER} already correct ({', '.join(stems) or 'empty'})")
        return 0

    with open(alphax, "wb") as fh:
        fh.write(new.encode("cp1252", errors="replace"))
    print(f"  registered in {MARKER}: {', '.join(stems) or 'none'}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--alphax", required=True)
    ap.add_argument("--factions", required=True,
                    help="directory holding the custom faction .TXT files")
    ap.add_argument("--check", action="store_true",
                    help="report without writing; non-zero exit if wrong")
    args = ap.parse_args()

    if not os.path.exists(args.alphax):
        sys.exit(f"no alphax.txt at {args.alphax}")
    stems = faction_stems(args.factions)
    return rewrite(args.alphax, stems, args.check)


if __name__ == "__main__":
    sys.exit(main())
