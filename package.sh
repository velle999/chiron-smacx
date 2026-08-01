#!/usr/bin/env bash
# Build a distributable zip: everything needed to install the mod on a machine
# with no compiler, laid out so it unpacks straight into the game folder.
#
# Thinker's data files go in because they are part of the build, not extras --
# this is a master build (v5.4-6-g1eda847) and its modmenu.txt carries labels
# the released v5.4 file does not have. Shipping the DLL without them produces
# "Unable to allocate draw-buffer" at startup. See README Troubleshooting.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FORK="$SRC/thinker-chiron"
BUILD="$FORK/build/gcc14"
OUT="$SRC/dist"

[ -f "$BUILD/thinker.dll" ] || {
    echo "error: no GCC 14 build at $BUILD" >&2
    echo "       see docs/toolchain.md -- a UCRT build does not run" >&2
    exit 1
}

# Refuse to ship a DLL built by the wrong toolchain. The import table is the
# cheap half of the check; it is necessary but not sufficient, so this only
# catches the obvious failure.
if i686-w64-mingw32-objdump -p "$BUILD/thinker.dll" | grep -qi 'api-ms-win-crt'; then
    echo "error: thinker.dll imports the UCRT. It will not run." >&2
    exit 1
fi
if i686-w64-mingw32-objdump -p "$BUILD/thinker.dll" | grep -qi 'WS2_32'; then
    echo "error: thinker.dll statically imports WS2_32; winsock must load lazily." >&2
    exit 1
fi

VER="$(git -C "$FORK" describe --tags --always 2>/dev/null || echo unknown)"
NAME="ChironRising-$VER"
STAGE="$OUT/$NAME"

rm -rf "$STAGE"
mkdir -p "$STAGE"

install -m644 "$BUILD/thinker.dll" "$STAGE/thinker.dll"
install -m755 "$BUILD/thinker.exe" "$STAGE/thinker.exe"
install -m644 "$SRC/chiron.ini"    "$STAGE/chiron.ini"
install -m755 "$SRC/install.sh"    "$STAGE/install.sh"
install -m755 "$SRC/patch-imports.py" "$STAGE/patch-imports.py"
install -m644 "$SRC/README.md"     "$STAGE/README.md"

# Thinker's data files, matching the DLL.
for f in modmenu.txt alphax.txt thinker.ini; do
    [ -f "$FORK/docs/$f" ] && install -m644 "$FORK/docs/$f" "$STAGE/$f"
done
for d in basenames smac_mod german; do
    [ -d "$FORK/docs/$d" ] || continue
    mkdir -p "$STAGE/$d"
    cp -p "$FORK/docs/$d"/*.txt "$STAGE/$d/" 2>/dev/null || true
done

mkdir -p "$STAGE/bridge"
cp -p "$SRC/bridge/chiron-bridge.py" "$SRC/bridge/chiron-bridge.service" "$STAGE/bridge/"

mkdir -p "$STAGE/docs"
cp -p "$SRC/docs/toolchain.md" "$STAGE/docs/" 2>/dev/null || true

install -m644 "$FORK/License.md" "$STAGE/License-Thinker.md"

# python's zipfile rather than zip(1): Arch does not ship zip by default, and
# python3 is already a hard dependency via patch-imports.py.
rm -f "$OUT/$NAME.zip"
python3 - "$OUT" "$NAME" <<'PY'
import os, sys, zipfile
out, name = sys.argv[1], sys.argv[2]
root = os.path.join(out, name)
with zipfile.ZipFile(os.path.join(out, name + ".zip"), "w", zipfile.ZIP_DEFLATED) as z:
    for dirpath, _, files in os.walk(root):
        for f in sorted(files):
            full = os.path.join(dirpath, f)
            z.write(full, os.path.relpath(full, out))
PY
echo "built $OUT/$NAME.zip"
python3 -c "import zipfile,sys; z=zipfile.ZipFile(sys.argv[1]); print(len(z.namelist()), 'files,', sum(i.file_size for i in z.infolist())//1024, 'KiB uncompressed')" "$OUT/$NAME.zip"
