#!/usr/bin/env bash
# Swap the installed thinker.dll between the Chiron build and a zero-Chiron
# control, and clear the traces, so each launch is a clean single-variable test.
#
# The failure being chased ("Unable to allocate draw-buffer; terminating
# program") looks identical no matter what causes it, and at least three
# different things produce it. Reasoning about it from the message has burned
# several launches. Swapping one binary at a time is the only method that has
# actually isolated anything here.
#
#   ./ab.sh release   upstream's SHIPPED v5.4 dll -- the known-good binary
#   ./ab.sh control   zero-Chiron local build     -- if this fails, Chiron is innocent
#   ./ab.sh chiron    current build               -- the mod as it stands
#   ./ab.sh vanilla   no thinker.dll at all       -- unmodded terranx
#   ./ab.sh status    what is installed right now
#
# release vs control is the load-bearing comparison: same source, different
# compiler. Upstream ships a GCC 14.2.0 MinGW-Builds binary; Arch's toolchain is
# GCC 16.1.0 and defaults to UCRT. If release works and control does not, the
# toolchain is the fault and no amount of editing chiron.cpp will help.
set -euo pipefail

DEFAULT_GAME="$HOME/.local/share/Steam/steamapps/common/Sid Meier's Alpha Centauri"
GAME="${GAME:-$DEFAULT_GAME}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTROL="$SRC/thinker.dll.upstream-msvcrt-control"
RELEASE="$SRC/reference/thinker-v5.4-release.dll"

# Prefer the GCC 14 build. build/release is Arch's GCC 16 output, kept only so
# the two can still be compared; it does not launch. See docs/toolchain.md.
BUILT="$SRC/thinker-chiron/build/gcc14/thinker.dll"
[ -f "$BUILT" ] || BUILT="$SRC/thinker-chiron/build/release/thinker.dll"

sha() { sha1sum "$1" 2>/dev/null | cut -c1-12; }

clear_traces() {
    rm -f "$GAME/chiron_trace.txt" "$GAME/chiron.txt" "$GAME/chiron_gen.txt" "$GAME/debug.txt"
}

case "${1:-status}" in
release)
    [ -f "$RELEASE" ] || { echo "error: no release DLL at $RELEASE" >&2; exit 1; }
    install -m644 "$RELEASE" "$GAME/thinker.dll"
    python3 "$SRC/patch-imports.py" "$GAME/terranx.exe" >/dev/null
    clear_traces
    echo "installed UPSTREAM RELEASE v5.4  $(sha "$GAME/thinker.dll")"
    echo "known-good binary, GCC 14.2.0 MinGW-Builds. No Chiron code."
    ;;
control)
    [ -f "$CONTROL" ] || { echo "error: no control DLL at $CONTROL" >&2; exit 1; }
    install -m644 "$CONTROL" "$GAME/thinker.dll"
    # terranx.exe must still import thinker.dll, or nothing loads at all.
    python3 "$SRC/patch-imports.py" "$GAME/terranx.exe" >/dev/null
    clear_traces
    echo "installed CONTROL (no Chiron code)  $(sha "$GAME/thinker.dll")"
    echo "expect: no chiron_trace.txt at all, since the control cannot write one."
    ;;
chiron)
    [ -f "$BUILT" ] || { echo "error: no build at $BUILT" >&2; exit 1; }
    install -m644 "$BUILT" "$GAME/thinker.dll"
    python3 "$SRC/patch-imports.py" "$GAME/terranx.exe" >/dev/null
    clear_traces
    echo "installed CHIRON  $(sha "$GAME/thinker.dll")"
    ;;
vanilla)
    # Restores the unpatched import table, so terranx loads SHELL32 as shipped
    # and no thinker.dll is involved even if one is sitting in the folder.
    python3 "$SRC/patch-imports.py" "$GAME/terranx.exe" --restore
    clear_traces
    echo "restored VANILLA terranx.exe (thinker.dll not loaded)"
    ;;
status)
    printf 'installed thinker.dll : %s\n' "$(sha "$GAME/thinker.dll")"
    printf '  control build       : %s\n' "$(sha "$CONTROL")"
    printf '  chiron build        : %s\n' "$(sha "$BUILT")"
    # grep -q exits on first match and SIGPIPEs objdump, which under `set -o
    # pipefail` makes the whole pipeline report failure -- so capture first,
    # then match. Getting this backwards reports a patched exe as vanilla.
    imports=$(i686-w64-mingw32-objdump -p "$GAME/terranx.exe" 2>/dev/null || true)
    case "$imports" in
        *thinker.dll*) printf 'terranx imports       : thinker.dll (patched)\n' ;;
        *)             printf 'terranx imports       : SHELL32.dll (vanilla)\n' ;;
    esac
    echo "--- chiron_trace.txt ---"
    cat "$GAME/chiron_trace.txt" 2>/dev/null || echo "(none)"
    ;;
*)
    echo "usage: $0 {release|control|chiron|vanilla|status}" >&2
    exit 1
    ;;
esac
