#!/usr/bin/env python3
"""Structurally validate a faction file against the vanilla ones.

The engine parses the header block POSITIONALLY -- the rhetoric strings are
identified by their line offset from the stat line, not by any label. A file
one line short parses every string one slot early and the faction talks
nonsense, with no error anywhere. So the check that matters is: does the block
have exactly as many lines as a shipped faction's?

    ./validate.py SUFFIC.TXT ORACLE.TXT
"""
import sys, os, re

GAME = os.environ.get(
    "GAME",
    os.path.expanduser(
        "~/.local/share/Steam/steamapps/common/Sid Meier's Alpha Centauri"))

# The 11 legal social effects, from alphax.txt #SOCIO.
EFFECTS = {"ECONOMY", "EFFIC", "SUPPORT", "TALENT", "MORALE", "POLICE",
           "GROWTH", "PLANET", "PROBE", "INDUSTRY", "RESEARCH"}

# Rule keywords documented in FACTION.TXT.
RULES = {"TECH", "MORALE", "PSI", "FACILITY", "RESEARCH", "DRONE", "TALENT",
         "ENERGY", "INTEREST", "COMMERCE", "POPULATION", "HURRY", "UNIT",
         "TECHCOST", "SHARETECH", "TECHSHARE", "TERRAFORM", "SOCIAL", "ROBUST",
         "IMMUNITY", "IMPUNITY", "PENALTY", "FUNGNUTRIENT", "FUNGMINERALS",
         "FUNGENERGY", "COMMFREQ", "MINDCONTROL", "FANATIC", "VOTES",
         "FREEPROTO", "ALIEN", "DEFENSE", "OFFENSE", "AQUATIC", "FREEFAC",
         "FREEABIL", "NODRONE", "REVOLT", "PROBECOST", "TECHSTEAL",
         "WORMPOLICE", "FUNGROAD"}

SECTIONS = ["#BASES", "#WATERBASES", "#BLURB", "#DATALINKS1", "#DATALINKS2",
            "#FACTIONTRUCE", "#FACTIONTREATY"]


def header_block(path):
    """Lines from the #LABEL line to the first #BASES, blanks stripped."""
    out, started = [], False
    with open(path, newline="") as fh:
        for raw in fh:
            line = raw.rstrip("\r\n")
            if re.match(r"^#[A-Z0-9]+$", line.strip()) and not started:
                started, out = True, [line.strip()]
                continue
            if started:
                if line.strip() == "#BASES":
                    break
                if line.strip():
                    out.append(line)
    return out


def check(path, baseline_len):
    name = os.path.basename(path)
    errs, warns = [], []
    text = open(path, newline="").read()
    block = header_block(path)

    if not block:
        return [f"{name}: no #LABEL header block found"], []

    label = block[0]
    stem = os.path.splitext(name)[0].upper()
    if label != "#" + stem:
        errs.append(f"{label} does not match filename stem #{stem} "
                    f"-- the engine looks the faction up by filename")

    if len(block) != baseline_len:
        errs.append(f"header block is {len(block)} lines, vanilla is "
                    f"{baseline_len} -- rhetoric strings are positional, so "
                    f"every line after the gap is read into the wrong slot")

    # stat line: 12 comma-separated fields before the trailing comma
    fields = [f.strip() for f in block[1].split(",")]
    fields = [f for f in fields if f != ""]
    if len(fields) != 12:
        errs.append(f"stat line has {len(fields)} fields, expected 12 "
                    f"(formal..ai-growth)")
    else:
        if fields[3] not in ("M", "F"):
            errs.append(f"masc/fem is {fields[3]!r}, expected M or F")
        if fields[4] not in ("1", "2"):
            errs.append(f"sing/plural is {fields[4]!r}, expected 1 or 2")
        if fields[6] not in ("M", "F"):
            errs.append(f"leader gender is {fields[6]!r}, expected M or F")
        if fields[7] not in ("-1", "0", "1"):
            errs.append(f"ai-fight is {fields[7]!r}, expected -1, 0 or 1")
        for i, nm in ((8, "ai-power"), (9, "ai-tech"), (10, "ai-wealth"),
                      (11, "ai-growth")):
            if fields[i] not in ("0", "1"):
                errs.append(f"{nm} is {fields[i]!r}, expected 0 or 1")

    # rules line
    toks = [t.strip() for t in block[2].split(",")]
    i = 0
    while i < len(toks):
        kw = toks[i]
        if not kw:
            i += 1
            continue
        if kw not in RULES:
            errs.append(f"unknown rule keyword {kw!r}")
            i += 2
            continue
        if kw == "SOCIAL":
            eff = toks[i + 1] if i + 1 < len(toks) else ""
            bare = eff.lstrip("+-")
            if bare not in EFFECTS:
                errs.append(f"SOCIAL, {eff!r} is not one of the 11 #SOCIO "
                            f"effects")
            if len(eff) - len(bare) > 3:
                warns.append(f"SOCIAL, {eff} is more than 3 steps")
        i += 2

    for sec in SECTIONS:
        if sec not in text:
            errs.append(f"missing {sec} section")

    if "#END" not in text:
        errs.append("no #END terminator on the base lists")

    if not text.rstrip().endswith("# ; This line must remain at end of file"):
        warns.append("missing the trailing sentinel comment vanilla files end on")

    if "\r\n" not in text:
        warns.append("file is LF; vanilla faction files are CRLF")

    return errs, warns


def main():
    ref = os.path.join(GAME, "GAIANS.TXT")
    if not os.path.exists(ref):
        print(f"baseline not found: {ref}", file=sys.stderr)
        return 2
    baseline = len(header_block(ref))
    print(f"baseline: GAIANS.TXT header block = {baseline} lines\n")

    rc = 0
    for path in sys.argv[1:]:
        errs, warns = check(path, baseline)
        name = os.path.basename(path)
        if not errs and not warns:
            print(f"  OK    {name}")
        for w in warns:
            print(f"  warn  {name}: {w}")
        for e in errs:
            print(f"  FAIL  {name}: {e}")
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
