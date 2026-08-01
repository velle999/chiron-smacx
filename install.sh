#!/usr/bin/env bash
# Install the Chiron Rising mod pack over an existing SMACX install.
#
# Additive and reversible: Thinker never writes to terranx.exe, and anything
# this overwrites is copied to _vanilla_backup/ first.
set -euo pipefail

# The apostrophe in "Sid Meier's" cannot live inside a ${VAR:-default}
# expansion -- bash parses it as an opening quote even within double quotes.
DEFAULT_GAME="$HOME/.local/share/Steam/steamapps/common/Sid Meier's Alpha Centauri"
GAME="${GAME:-$DEFAULT_GAME}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The GCC 14 build is the one that runs. Arch's mingw-w64 (GCC 16, UCRT-native)
# produces a DLL that imports msvcrt.dll yet still dies at startup with
# "Unable to allocate draw-buffer". See docs/toolchain.md.
BUILD="$SRC/thinker-chiron/build/gcc14"
[ -f "$BUILD/thinker.dll" ] || BUILD="$SRC/thinker-chiron/build/release"

if [ ! -f "$GAME/terranx.exe" ]; then
    echo "error: no terranx.exe in $GAME" >&2
    echo "set GAME=/path/to/alpha-centauri and retry" >&2
    exit 1
fi
if [ ! -f "$BUILD/thinker.dll" ]; then
    echo "error: no build found. Run:" >&2
    echo "  cd $SRC/thinker-chiron && cmake --preset release && cmake --build --preset release" >&2
    exit 1
fi

# SMAC's Buffer_copy crashes on dimensions that are not multiples of 8, and the
# only symptom is "unable to allocate draw buffer, terminating program" -- no
# log, no hint that the resolution is at fault. Catch it here instead.
if [ -f "$GAME/thinker.ini" ]; then
    W=$(sed -n 's/^window_width=\([0-9]*\).*/\1/p'  "$GAME/thinker.ini" | tail -1)
    H=$(sed -n 's/^window_height=\([0-9]*\).*/\1/p' "$GAME/thinker.ini" | tail -1)
    for pair in "width:$W" "height:$H"; do
        name=${pair%%:*}; val=${pair#*:}
        if [ -n "$val" ] && [ $((val % 8)) -ne 0 ]; then
            echo "error: thinker.ini window_$name=$val is not a multiple of 8." >&2
            echo "       The game will die with 'unable to allocate draw buffer'." >&2
            exit 1
        fi
    done
fi

mkdir -p "$GAME/_vanilla_backup"
for f in alphax.txt tutor.txt helpx.txt conceptsx.txt modmenu.txt "Alpha Centauri.Ini"; do
    if [ -f "$GAME/$f" ] && [ ! -f "$GAME/_vanilla_backup/$f" ]; then
        cp -p "$GAME/$f" "$GAME/_vanilla_backup/$f"
        echo "backed up $f"
    fi
done

# Thinker's data files are part of the build, not optional extras. The DLL asks
# modmenu.txt for labels by name, and a version that predates the code silently
# has none of them -- game.cpp:591 requests #TOPMENU while building the opening
# menu, and on a v5.4 modmenu.txt that lookup fails right where the splash is
# drawn. It surfaces as "Unable to allocate draw-buffer; terminating program",
# with nothing pointing at a text file.
#
# Upstream ships these in the release zip for exactly this reason. thinker.ini
# is deliberately NOT overwritten: it holds the user's video settings, and new
# options fall back to their defaults when absent.
DOCS="$SRC/thinker-chiron/docs"
for f in modmenu.txt alphax.txt; do
    if [ -f "$DOCS/$f" ]; then
        install -m644 "$DOCS/$f" "$GAME/$f"
        echo "installed $f (Thinker's, matching the DLL)"
    fi
done
for d in basenames smac_mod german; do
    if [ -d "$DOCS/$d" ]; then
        mkdir -p "$GAME/$d"
        cp -p "$DOCS/$d"/*.txt "$GAME/$d/" 2>/dev/null || true
    fi
done

# Chiron's own factions. The picker reads the game directory, so a faction is
# installed by being present -- there is no list to register it in. These add
# files rather than replacing any, so there is nothing to back up and nothing
# to restore: uninstalling a faction is deleting its .TXT from the game folder.
#
# The base-name pools go in basenames/ beside the stock ones because Chiron
# few-shots generated base names from the faction's own list, and a faction
# with no list there gets welded-together slogans instead of names.
if [ -d "$SRC/factions" ]; then
    for f in "$SRC/factions"/*.TXT; do
        [ -f "$f" ] || continue
        install -m644 "$f" "$GAME/$(basename "$f")"
        echo "installed faction $(basename "$f")"
    done
    if [ -d "$SRC/factions/basenames" ]; then
        mkdir -p "$GAME/basenames"
        cp -p "$SRC/factions/basenames"/*.txt "$GAME/basenames/" 2>/dev/null || true
    fi
fi

install -m644 "$BUILD/thinker.dll" "$GAME/thinker.dll"
install -m644 "$SRC/chiron.ini"    "$GAME/chiron.ini"
# The launcher is optional and usually absent: thinker.exe does not link here
# (launch.cpp wants _imp___vsnprintf, which no msvcrt-os library on this box
# provides), and nothing needs it -- patch-imports.py below makes terranx.exe
# load the DLL by itself, so Steam's Play button is the launcher. Copy it when a
# build happens to have one, but never fail the install over it.
if [ -f "$BUILD/thinker.exe" ]; then
    install -m755 "$BUILD/thinker.exe" "$GAME/thinker.exe"
fi
echo "installed thinker.dll (chiron build), chiron.ini"

# Redirect one import so Steam's Play button loads the mod without a launcher.
# Keeps a .vanilla copy; undo with --restore or Steam's file verification.
python3 "$SRC/patch-imports.py" "$GAME/terranx.exe"

# User service so the bridge is up whenever the game is; without it the mod
# quietly falls back to the game's original dialogue.
UNIT="$HOME/.config/systemd/user"
mkdir -p "$UNIT"
install -m644 "$SRC/bridge/chiron-bridge.service" "$UNIT/chiron-bridge.service"
systemctl --user daemon-reload
systemctl --user enable --now chiron-bridge.service
echo "chiron-bridge: $(systemctl --user is-active chiron-bridge.service)"

echo
echo "Launch the game from Steam as usual."
echo "In game, Ctrl+F4 shows the mod version; Alt+T opens Thinker's options."
