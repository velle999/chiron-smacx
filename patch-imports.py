#!/usr/bin/env python3
"""
Make terranx.exe load thinker.dll at startup, so the mod comes up from Steam's
normal Play button with no separate launcher.

Thinker's documented loader (thinker.exe) CreateProcess's the game and injects
the DLL. That needs to run the exe directly, which is awkward under Proton --
Steam owns the runtime container, the prefix and the environment. The
alternative Thinker documents in Technical.md is to redirect one import:

    SHELL32.dll   -> thinker.dll      (both 11 chars)
    ShellExecuteA -> ThinkerModule    (both 13 chars)

Windows resolves imports before the entry point runs, so thinker.dll loads and
patches the in-memory image exactly as it would under the launcher. The lengths
match, so this is an in-place byte swap that does not disturb the PE layout.

The game only used ShellExecuteA to open URLs, which is why Thinker picks this
import to steal.

Reversible: --restore, or Steam's "Verify integrity of game files".
"""
import argparse
import os
import shutil
import sys

PAIRS = [(b"SHELL32.dll", b"thinker.dll"),
         (b"ShellExecuteA", b"ThinkerModule")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("exe")
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args()

    backup = args.exe + ".vanilla"

    if args.restore:
        if not os.path.exists(backup):
            print(f"error: no backup at {backup}", file=sys.stderr)
            return 1
        shutil.copy2(backup, args.exe)
        print(f"restored {args.exe} from {backup}")
        return 0

    data = bytearray(open(args.exe, "rb").read())

    already = all(data.count(new) for _, new in PAIRS)
    if already:
        print("already patched; nothing to do")
        return 0

    for old, new in PAIRS:
        assert len(old) == len(new), "replacement must not change PE layout"
        n = data.count(old)
        if n == 0:
            print(f"error: {old.decode()} not found -- wrong or already-modified exe",
                  file=sys.stderr)
            return 1
        data = bytearray(data.replace(old, new))
        print(f"{old.decode()} -> {new.decode()}  ({n} occurrence{'s'[:n^1]})")

    if not os.path.exists(backup):
        shutil.copy2(args.exe, backup)
        print(f"backed up vanilla exe to {backup}")

    tmp = args.exe + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    shutil.copymode(args.exe, tmp)
    os.replace(tmp, args.exe)
    print(f"patched {args.exe}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
