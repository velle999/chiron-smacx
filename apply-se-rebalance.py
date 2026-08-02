#!/usr/bin/env python3
"""Apply the optional Future Society repricing to an installed alphax.txt.

Replacement rows and the reasoning live in se-rebalance.txt. This only splices
them in, and only inside the #SOCIO block: the model names also occur in tech
names and datalinks prose elsewhere in the file, so a whole-file search-replace
would rewrite text that has nothing to do with the social table.

Line endings are preserved. The shipped alphax.txt is CRLF in the release zip
and LF in git -- same content, .gitattributes does it -- and rewriting a file
into the other convention is the kind of diff that looks like a data change.

    ./apply-se-rebalance.py <gamedir>/alphax.txt [--rows se-rebalance.txt]
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def replacement_rows(path):
    """The uncommented, non-blank lines at the end of se-rebalance.txt."""
    rows = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            name = line.split(",")[0].strip()
            rows[name] = line
    return rows


def socio_bounds(lines):
    """Index range of the #SOCIO block's body, exclusive of the header."""
    start = None
    for i, line in enumerate(lines):
        if line.strip().upper() == "#SOCIO":
            start = i + 1
            break
    if start is None:
        raise SystemExit("error: no #SOCIO block in the target file")
    for j in range(start, len(lines)):
        # The next section header ends the block.
        if re.match(r"^#[A-Za-z]", lines[j].strip()):
            return start, j
    return start, len(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="alphax.txt to patch, in place")
    ap.add_argument("--rows", default=os.path.join(HERE, "se-rebalance.txt"))
    args = ap.parse_args()

    rows = replacement_rows(args.rows)
    if not rows:
        raise SystemExit("error: no replacement rows in %s" % args.rows)

    with open(args.target, newline="") as fh:
        text = fh.read()
    lines = text.splitlines(keepends=True)

    start, end = socio_bounds(lines)
    done = []
    for i in range(start, end):
        raw = lines[i]
        name = raw.split(",")[0].strip()
        if name in rows:
            # Keep this line's own ending, whatever the rest of the file uses.
            ending = raw[len(raw.rstrip("\r\n")):]
            lines[i] = rows[name] + ending
            done.append(name)

    missing = [n for n in rows if n not in done]
    if missing:
        raise SystemExit(
            "error: %s not found in the #SOCIO block -- is this a stock "
            "alphax.txt?" % ", ".join(sorted(missing)))

    with open(args.target, "w", newline="") as fh:
        fh.write("".join(lines))
    print("repriced %d Future Society rows: %s" % (len(done), ", ".join(done)))


if __name__ == "__main__":
    sys.exit(main())
