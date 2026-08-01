# Toolchain

Thinker must be built by a compiler that targets **msvcrt**, and Arch's
mingw-w64 is not one. This is not a preference; a UCRT-targeting toolchain
produces a DLL that loads and then kills the game.

## Why

`thinker.dll` is injected into a 1999 binary and shares `FILE*` handles and heap
allocations with it directly. The game is built against `msvcrt.dll`. A DLL
built against the Universal CRT gets its own heap and an incompatible `FILE`
layout, and the game's `CreateDIBSection` then returns NULL.

The symptom is **"Unable to allocate draw-buffer; terminating program"** after
the music and the Alien Crossfire splash. It looks exactly like a graphics or
resolution problem and is not one.

Three unrelated faults produce that identical message, which is what makes it
so expensive to diagnose:

1. a UCRT build (this page),
2. a `thinker.ini` window dimension not divisible by 8 (`valid_resolution()`
   in `patch.cpp` rejects it; 900 fails, 1080 and 1440 pass),
3. a static `ws2_32` import loading the winsock chain before the game reserves
   its draw buffer (fixed in `186a257`/`7e26dd1`).

Read the message as "something is wrong", never as "the resolution is wrong".

## What does not work

`-mcrtdll=msvcrt-os` on Arch's GCC. It flips the import table to `msvcrt.dll`,
so the usual check passes:

    i686-w64-mingw32-objdump -p thinker.dll | grep 'DLL Name'

...and the game still dies. The import is only the visible half. libstdc++ is
still a UCRT libstdc++, `<cstdlib>` needs `at_quick_exit`/`quick_exit` shims to
compile at all (`src/msvcrt_compat.*`), and the linked output differs
structurally from a real msvcrt build — upstream's shipped DLL carries a `.CRT`
section that no Arch build produces. **A `msvcrt.dll` import is necessary but
nowhere near sufficient.** CMakeLists keeps this path only as a fallback, and
warns when it takes it.

## What works

Debian's cross-compiler: GCC 14.2.0, Linux-hosted, msvcrt by default — the same
GCC major version as upstream's MinGW-Builds `i686-posix-dwarf-rev1 14.2.0`.
It needs no root and touches no system package.

    cd ~/toolchains
    curl -sSLO https://deb.debian.org/debian/dists/trixie/main/binary-amd64/Packages.gz
    # download these from https://deb.debian.org/debian/<Filename>:
    #   binutils-mingw-w64-i686           g++-mingw-w64-i686-win32
    #   gcc-mingw-w64-base                gcc-mingw-w64-i686-win32
    #   gcc-mingw-w64-i686-win32-runtime  mingw-w64-common
    #   mingw-w64-i686-dev
    for d in debs/*.deb; do ar p "$d" data.tar.xz | tar -xJ -C mingw14; done
    # symlink the -win32 suffixed drivers to plain names in ~/toolchains/bin14

Configure against it:

    cmake -S . -B build/gcc14 -G "Unix Makefiles" -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_SYSTEM_NAME=Windows \
      -DCMAKE_C_COMPILER=$HOME/toolchains/bin14/i686-w64-mingw32-gcc \
      -DCMAKE_CXX_COMPILER=$HOME/toolchains/bin14/i686-w64-mingw32-g++ \
      -DCMAKE_RC_COMPILER=$HOME/toolchains/bin14/i686-w64-mingw32-windres

CMakeLists probes for `_UCRT` and skips every workaround when the toolchain is
natively msvcrt. Configure output should say:

    -- Performing Test MOD_CRT_IS_MSVCRT - Success

`install.sh` and `ab.sh` both prefer `build/gcc14` and fall back to
`build/release` only if it is missing.

## Bisecting a startup failure

Reasoning about the draw-buffer message from the message alone has never once
been productive here. Swap binaries instead, one variable per launch:

    ./ab.sh release   upstream's shipped v5.4 -- known-good, no Chiron code
    ./ab.sh control   our build, no Chiron code
    ./ab.sh chiron    the mod
    ./ab.sh vanilla   unpatched terranx, no thinker.dll at all
    ./ab.sh status    what is installed, plus the current trace

`release` vs `control` is the load-bearing comparison: identical source,
different compiler. If `release` runs and `control` does not, the toolchain is
at fault and no amount of editing the mod will help.

`chiron_trace.txt` in the game folder records how far the process got, with no
configuration behind it. Its last line is the answer; see `chiron_trace()` in
`src/chiron.h`.
