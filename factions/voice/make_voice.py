#!/usr/bin/env python3
"""Synthesise a faction's opening speech with Piper.

The stock factions ship voices/<stem>.mp3 -- the leader reading their blurb
when you pick them. Custom factions have never had one (BRIAN and SID, the
hidden factions in the base game, ship no mp3 at all), so the pick screen is
silent. The filename is keyed on the faction stem, though, so supplying the
file is all it takes.

Text comes from the faction file's own #BLURB, which is exactly the passage the
stock voices read. The attribution lines (leading '^') are formatting, not
speech, and are dropped.

Piper lives inside the chibi package rather than on PATH, and there is one
installed voice, so the two leaders are separated by pitch and tempo instead of
by model. Output matches the shipped files: mp3, 22050 Hz, mono, 64 kbps.

    ./make_voice.py suffic --factions .. --install "$GAME"
    ./make_voice.py oracle --factions .. --play
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

PIPER_PYTHONPATH = "/usr/lib/chibi/pydeps"
VOICE_MODEL = "/usr/share/piper-voices/en_GB-cori-medium.onnx"

# One installed voice, two leaders. Kaya is unhurried and warm; Ravn is precise
# and cold, and reads slightly fast because she is not waiting for you.
TREATMENT = {
    "suffic": ["pitch", "-110", "tempo", "-s", "0.94"],
    "oracle": ["pitch", "90", "tempo", "-s", "1.05"],
    # Vashti sits between them on purpose: warmer and lower than Ravn, quicker
    # than Kaya. She is comfortable, and never sounds like she is being pressed.
    "assure": ["pitch", "-40", "tempo", "-s", "0.98"],
}


def blurb(faction_file):
    """The #BLURB body, minus the '^' attribution lines."""
    with open(faction_file, "rb") as fh:
        text = fh.read().decode("cp1252", errors="replace")
    m = re.search(r"(?m)^#BLURB[ \t\r]*$", text)
    if not m:
        sys.exit(f"no #BLURB in {faction_file}")
    tail = text[m.end():]
    nxt = re.search(r"(?m)^#[A-Z]", tail)
    body = tail[:nxt.start()] if nxt else tail

    lines = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("^"):
            continue
        lines.append(line)
    if not lines:
        sys.exit(f"#BLURB in {faction_file} has no spoken lines")
    return " ".join(lines)


def run(cmd, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if p.returncode:
        sys.exit(f"{cmd[0]} failed:\n{p.stderr.strip()[:600]}")
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("faction")
    ap.add_argument("--factions", default="..",
                    help="directory holding the faction .TXT files")
    ap.add_argument("--model", default=VOICE_MODEL)
    ap.add_argument("--install", help="game directory; writes voices/<stem>.mp3")
    ap.add_argument("--play", action="store_true")
    ap.add_argument("--outdir", default=os.path.dirname(os.path.abspath(__file__)))
    args = ap.parse_args()

    key = args.faction.lower()
    if not os.path.exists(args.model):
        sys.exit(f"no piper voice at {args.model}")

    src = None
    for cand in os.listdir(args.factions):
        if cand.lower() == f"{key}.txt":
            src = os.path.join(args.factions, cand)
            break
    if not src:
        sys.exit(f"no faction file for {key} in {args.factions}")

    text = blurb(src)
    print(f"  {len(text.split())} words: {text[:72]}...")

    env = dict(os.environ, PYTHONPATH=PIPER_PYTHONPATH)
    with tempfile.TemporaryDirectory() as tmp:
        raw = os.path.join(tmp, "raw.wav")
        shaped = os.path.join(tmp, "shaped.wav")
        run([sys.executable, "-m", "piper", "--model", args.model,
             "--output-file", raw], input=text, env=env)

        fx = TREATMENT.get(key)
        if fx:
            run(["sox", raw, shaped] + fx)
        else:
            shutil.copy2(raw, shaped)

        out = os.path.join(args.outdir, f"{key}.mp3")
        # 22050 Hz mono 64k -- the format every shipped voice file uses.
        run(["ffmpeg", "-y", "-i", shaped, "-ar", "22050", "-ac", "1",
             "-b:a", "64k", "-codec:a", "libmp3lame", out])

    dur = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", out],
        capture_output=True, text=True).stdout.strip()
    print(f"  wrote {os.path.basename(out)}  {float(dur):.1f}s  "
          f"{os.path.getsize(out)} B")

    if args.install:
        dst = os.path.join(args.install, "voices", f"{key}.mp3")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(out, dst)
        print(f"  installed -> voices/{key}.mp3")

    if args.play:
        subprocess.run(["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", out])


if __name__ == "__main__":
    main()
