#!/usr/bin/env python3
"""Choose which seven factions play.

TWO DIFFERENT CAPS, and only one of them is real:

  * How many factions play in ONE GAME is SEVEN, and it cannot be modded.
    struct Faction carries 22 arrays of [8] (diplo_status, loan_balance,
    diplo_wrongs, ...) and MFaction another 5. An eighth playable faction
    widens all 27, which changes sizeof(Faction) -- and every faction access
    in terranx.exe is a compiled immediate of the form base + id*stride +
    offset, with the same structs embedded in the save format. Chiron's own
    chiron_warned_turn[8] was carved out of MFaction's reserved pad_1
    (96 -> 80 bytes) precisely so the struct size would NOT move.

  * How many factions EXIST to choose among is unlimited. It is just files.
    prefs_fac_load() (config.cpp:1686) reads seven filenames out of
    "Alpha Centauri.Ini" when Prefs Format=12, and that list is data.

So modding in new factions works by building a library and rotating which
seven are active. A roster is a debate: which seven arguments are in the room
decides what the game is about, more than any single faction does.

    ./roster.py --list
    ./roster.py --set CYBORG PIRATES DRONE ORACLE SUFFIC CARETAKE USURPER
    ./roster.py --preset chiron
    ./roster.py --restore
"""
import argparse
import os
import re
import shutil
import sys

DEFAULT_GAME = os.path.expanduser(
    "~/.local/share/Steam/steamapps/common/Sid Meier's Alpha Centauri")

SLOTS = 7

PRESETS = {
    # The shipped expansion seven.
    "smacx": ["CYBORG", "PIRATES", "DRONE", "ANGELS", "FUNGBOY",
              "CARETAKE", "USURPER"],
    # The original seven.
    "smac": ["GAIANS", "HIVE", "UNIV", "MORGAN", "SPARTANS", "BELIEVE",
             "PEACE"],
    # Each new faction displaces its nearest neighbour, so no two factions in
    # the room are making the same argument: the Directorate takes the Angels'
    # information slot, the Sufficiency takes the Cult's anti-economy slot.
    "chiron": ["CYBORG", "PIRATES", "DRONE", "ORACLE", "SUFFIC",
               "CARETAKE", "USURPER"],
    # Seven incompatible answers to "what is a person for". No aliens, no
    # pirates -- every faction here wants the same planet for a stated reason.
    "ideologies": ["HIVE", "MORGAN", "PEACE", "BELIEVE", "UNIV", "SUFFIC",
                   "ORACLE"],
}


def ini_path(game):
    return os.path.join(game, "Alpha Centauri.Ini")


def read_lines(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    return raw.decode("cp1252", errors="replace"), raw


def current_roster(game):
    text, _ = read_lines(ini_path(game))
    out = {}
    for m in re.finditer(r"(?im)^Faction\s+([1-7])\s*=\s*(\S+)\s*$", text):
        out[int(m.group(1))] = m.group(2)
    return [out.get(i, "?") for i in range(1, SLOTS + 1)]


def prefs_format(game):
    text, _ = read_lines(ini_path(game))
    m = re.search(r"(?im)^Prefs Format\s*=\s*(\d+)", text)
    return int(m.group(1)) if m else None


def available(game):
    """Every faction file in the game folder: stem -> formal name."""
    found = {}
    for fn in sorted(os.listdir(game)):
        stem, ext = os.path.splitext(fn)
        if ext.lower() != ".txt":
            continue
        try:
            with open(os.path.join(game, fn), "rb") as fh:
                head = fh.read(4096).decode("cp1252", errors="replace")
        except OSError:
            continue
        # A faction file opens a block whose label is the filename stem, and
        # the next non-blank line is the stat line beginning with the formal
        # name. FACTION.TXT is the template and has no faction of its own.
        if stem.upper() == "FACTION":
            continue
        m = re.search(r"(?m)^#" + re.escape(stem.upper()) + r"\s*$", head,
                      re.IGNORECASE)
        if not m:
            continue
        rest = head[m.end():].lstrip("\r\n")
        first = rest.split("\n", 1)[0].strip()
        if "," not in first:
            continue
        found[stem.upper()] = first.split(",")[0].strip()
    return found


def set_roster(game, names, force=False):
    path = ini_path(game)
    fmt = prefs_format(game)
    if fmt != 12:
        print(f"warning: Prefs Format={fmt}, not 12. prefs_fac_load() only "
              f"reads the Faction lines when it is 12, so this edit will be "
              f"ignored.", file=sys.stderr)

    have = available(game)
    missing = [n for n in names if n.upper() not in have]
    if missing and not force:
        sys.exit(f"no faction file for: {', '.join(missing)}\n"
                 f"(--list shows what is installed; --force overrides)")

    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        sys.exit(f"duplicate faction in roster: {', '.join(sorted(dupes))}")

    backup = path + ".pre-roster"
    if not os.path.exists(backup):
        shutil.copy2(path, backup)
        print(f"backed up ini -> {os.path.basename(backup)}")

    text, _ = read_lines(path)
    newline = "\r\n" if "\r\n" in text else "\n"

    def sub(m):
        idx = int(m.group(1))
        return f"Faction {idx}={names[idx - 1].upper()}"

    # Match up to but NOT including the line terminator: the ini is CRLF, and
    # consuming the \r would rewrite the file's line endings as a side effect
    # of changing a roster.
    new, n = re.subn(r"(?im)^Faction\s+([1-7])\s*=[^\r\n]*", sub, text)
    if n != SLOTS:
        sys.exit(f"expected {SLOTS} Faction lines in the ini, rewrote {n} -- "
                 f"not touching the file")

    with open(path, "wb") as fh:
        fh.write(new.encode("cp1252", errors="replace"))
    print(f"roster set:{newline.join([''] + [f'  Faction {i+1}={v.upper()}' for i, v in enumerate(names)])}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", default=os.environ.get("GAME", DEFAULT_GAME))
    ap.add_argument("--list", action="store_true",
                    help="show installed factions and the active seven")
    ap.add_argument("--set", nargs=SLOTS, metavar="NAME",
                    help=f"set all {SLOTS} slots by faction filename stem")
    ap.add_argument("--preset", choices=sorted(PRESETS))
    ap.add_argument("--restore", action="store_true",
                    help="put back the roster from before the first change")
    ap.add_argument("--force", action="store_true",
                    help="allow a faction with no file in the game folder")
    args = ap.parse_args()

    if not os.path.isdir(args.game):
        sys.exit(f"no game directory: {args.game}")

    if args.restore:
        backup = ini_path(args.game) + ".pre-roster"
        if not os.path.exists(backup):
            sys.exit("no .pre-roster backup to restore from")
        shutil.copy2(backup, ini_path(args.game))
        print("restored the pre-roster ini")
        args.list = True

    if args.set:
        set_roster(args.game, args.set, args.force)
    elif args.preset:
        set_roster(args.game, PRESETS[args.preset], args.force)

    if args.list or not (args.set or args.preset or args.restore):
        have = available(args.game)
        active = [n.upper() for n in current_roster(args.game)]
        print(f"Prefs Format={prefs_format(args.game)}  "
              f"(must be 12 for the roster to be read)\n")
        print(f"active roster -- {SLOTS} slots, and {SLOTS} is not moddable:")
        for i, n in enumerate(active, 1):
            print(f"  {i}. {n:<10} {have.get(n, '(no faction file!)')}")
        bench = sorted(set(have) - set(active))
        print(f"\ninstalled but not playing ({len(bench)}):")
        for n in bench:
            print(f"     {n:<10} {have[n]}")
        print(f"\npresets: {', '.join(sorted(PRESETS))}")


if __name__ == "__main__":
    main()
