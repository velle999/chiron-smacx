# Chiron Rising — a mod pack for Alpha Centauri

Faction leaders in SMACX speak lines written on the spot by a local model,
instead of the ~1500 canned strings in `xscript.txt`. Built on
[Thinker](https://github.com/induktio/thinker) at `v5.4-6-g1eda847` — six
commits past the v5.4 release, because Chiron's interception point
(`text_open()`) only exists on master. Thinker also carries
[Scient's Unofficial Patch](https://github.com/DrazharLn/scient-unofficial-smacx-patch)
v2.0.

> Because this is a **master** build and not the release, Thinker's own data
> files must match the DLL — `modmenu.txt` in particular. `install.sh` handles
> it; see [Troubleshooting](#troubleshooting) for what happens when it doesn't.

The AI layer is ported from [Chiron Rising](https://github.com/velle999/Chiron-Rising)
— the character bibles from `src/llm/factionPersonalities.ts` and the prompt
construction from `llmClient.ts`.

## What this does and does not change

The engine's logic is untouched. The same demand is made, the same buttons
appear, the same treaty is signed or refused. Only the **wording** changes, and
only for faction-to-faction speech. Combat results, probe outcomes and event
popups keep their original text.

> Chiron Rising's *rules* — the social engineering table, the tech tree, the
> seven faction bonuses — are byte-for-byte vanilla SMAC. Porting them into
> `alphax.txt` would recreate the stock game, so this pack deliberately ships
> none of it. The dialogue layer is the part that was actually original.

Only the seven original factions have bibles. SMACX's factions (Angels,
Caretakers, Cyborgs, Drones, Pirates, Cult, Usurpers) keep vanilla dialogue.

## How it works

```
terranx.exe ──imports──> thinker.dll ──HTTP──> chiron-bridge ──unix socket──> synapd
```

`text_open()` is the single funnel every labelled text block in the game passes
through. Once the engine has seeked to a `#LABEL`, Chiron reads the vanilla
block, asks the model to rewrite its prose, and swaps the `FILE*` for one
holding the result. `text_get()` keeps `fgets()`ing lines and never knows.

**Nothing can come up blank.** A dead bridge, a slow model, an empty reply, or a
reply that lost a placeholder all mean "show the line the game shipped".

### Placeholders

Vanilla lines contain `$TOKEN`s the engine substitutes after load — `$TECH0` is
the tech being demanded, `$NUM0` the credits offered. Losing one would leave you
agreeing to a blank, so:

- **Data-carrying tokens are mandatory.** A reply that drops one is discarded.
- **`$TITLE` is optional.** It is a bare honorific, and models reliably collapse
  `$TITLE1 $NAME2` into `$NAME2`. Requiring it would mean never showing
  generated text at all.
- **Invented tokens are scrubbed.** The engine renders an unrecognised token
  literally, so a hallucinated `$HONORED_ONE` would be visible junk.

## Install

### From a release zip

Unpack it into the game folder and run `install.sh`. No compiler needed.

### From source

**The compiler matters.** Thinker must be built against **msvcrt**, and a
distro toolchain that defaults to UCRT will produce a DLL that loads and then
kills the game. Arch's mingw-w64 is one of those. See
[`docs/toolchain.md`](docs/toolchain.md) for the full story and a root-free
setup using Debian's GCC 14.2.0 cross-compiler.

```bash
cmake -S thinker-chiron -B thinker-chiron/build/gcc14 -G "Unix Makefiles" \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_SYSTEM_NAME=Windows \
  -DCMAKE_C_COMPILER=$HOME/toolchains/bin14/i686-w64-mingw32-gcc \
  -DCMAKE_CXX_COMPILER=$HOME/toolchains/bin14/i686-w64-mingw32-g++ \
  -DCMAKE_RC_COMPILER=$HOME/toolchains/bin14/i686-w64-mingw32-windres
cmake --build thinker-chiron/build/gcc14 -j"$(nproc)"
./install.sh
```

Configure must report `MOD_CRT_IS_MSVCRT - Success`. If it warns instead, stop
and fix the toolchain — the build will compile and link cleanly and then fail
at startup.

The installer backs up anything it overwrites to `<game>/_vanilla_backup/`,
installs Thinker's data files alongside the DLL, keeps `terranx.exe.vanilla`,
and enables the bridge as a user service. It leaves `thinker.ini` alone, since
that holds your video settings.

Then launch from Steam normally. `Ctrl+F4` shows the mod version; `Alt+T` opens
Thinker's options. If neither shows the mod, it did not load.

### Display

`thinker.ini` in the game folder:

| `video_mode` | |
|---|---|
| `0` | fullscreen at the primary monitor's native resolution |
| `1` | fullscreen at `window_width`×`window_height` |
| `2` | borderless windowed at those dimensions |

**Both dimensions must be divisible by 8.** `valid_resolution()` rejects
anything else, because the engine's `Buffer_copy` crashes on it — and the only
symptom is the draw-buffer error below, with no mention of resolution. 1080,
1440 and 1920 are fine; 900 is not.

On a compositor with an always-visible panel, `video_mode=0` sizes the window to
the *full* screen while the panel reserves part of it, so the bottom of the menu
falls off the edge — "EXIT GAME" and the copyright line disappear. Subtract the
panel's exclusive zone and round **down** to a multiple of 8:

```
2560x1440 screen − 28px panel = 2560x1412 usable
1412 % 8 = 4                  → use 1408
```

so `video_mode=2` with `2560x1408`. Rounding *up* to 1416 would exceed the
usable area; leaving it at 1412 trips the divisibility rule and the game dies
with the draw-buffer error instead of just looking wrong.

## Troubleshooting

### "Unable to allocate draw-buffer; terminating program"

The game plays its music, draws the Alien Crossfire splash, and dies. **This one
message has at least four unrelated causes**, and it never once indicates what
is actually wrong. Do not reason about it — bisect.

| Cause | Check |
|---|---|
| Thinker's data files don't match the DLL | `grep -c '^#TOPMENU' <game>/modmenu.txt` — a master build needs it |
| Built by a UCRT toolchain | `objdump -p thinker.dll \| grep 'DLL Name'` must show `msvcrt.dll`, **and** configure must have said `MOD_CRT_IS_MSVCRT - Success` |
| A window dimension not divisible by 8 | `thinker.ini` |
| Winsock loaded before the draw buffer is reserved | fixed; `WS2_32` must **not** appear in the import table |

An `msvcrt.dll` import is **necessary but not sufficient** — `-mcrtdll=msvcrt-os`
flips the import table while libstdc++ stays a UCRT libstdc++, so that check can
pass on a DLL that still cannot run.

### Bisecting

`ab.sh` swaps the installed DLL so each launch tests one variable:

```
./ab.sh release   upstream's shipped v5.4 — known-good, no Chiron code
./ab.sh control   our build, no Chiron code
./ab.sh chiron    the mod
./ab.sh vanilla   unpatched terranx, no thinker.dll at all
./ab.sh status    what is installed, plus the current trace
```

`release` vs `chiron` is the load-bearing comparison. Note that `release` is the
**v5.4** binary with **v5.4** data files, so swapping to it and back also swaps
what `modmenu.txt` needs to be — `install.sh` puts the right one back.

### chiron_trace.txt

Written unconditionally to the game folder, with no configuration behind it.
Its last line is how far the process got:

| | |
|---|---|
| *missing* | `thinker.dll` never loaded |
| `dllmain: attach` | loaded, died in Thinker's setup |
| `dllmain: patch_setup ok` | in-memory patching worked |
| `text_open: …` | reached its first text lookup |
| `init: …` | Chiron config came up |
| `hook: rewriting …` | a diplomacy label matched |
| `winsock: ready=…` | first generation attempted |

### Why the import patch

Thinker's own launcher (`thinker.exe`) starts the game and injects the DLL,
which means running the exe directly — awkward under Proton, where Steam owns
the runtime container, the prefix and the environment. So `install.sh` uses the
method from Thinker's `Technical.md` instead, redirecting one import:

```
SHELL32.dll   -> thinker.dll     (both 11 chars)
ShellExecuteA -> ThinkerModule   (both 13 chars)
```

Windows resolves imports before the entry point runs, so the DLL loads and
patches the in-memory image exactly as under the launcher. Lengths match, so the
PE layout is untouched. Undo with `patch-imports.py --restore`, or Steam's
"Verify integrity of game files".

`terranx.exe` is never otherwise modified — Thinker applies all of its own
changes, and Scient's, to the in-memory image at startup.

## Configuration

`chiron.ini`, installed into the game folder. Set `enabled=0` for stock Thinker,
or `debug=1` to get `chiron.txt` listing every label, whether it was rewritten,
and why anything was rejected.

## Tuning the writing

The backend is whatever `synapd` is serving — currently a 7B/q4. Quality is
decent at that size but the prompt does most of the work; `src/chiron.cpp`'s
`build_prompt()` is where to iterate. `scratchpad/sim_rewrite.py` mirrors the
whole rewrite path in Python so you can judge output without launching the game.

## Layout

| Path | |
|---|---|
| `thinker-chiron/` | Thinker fork, `chiron` branch. All new code in `src/chiron.{h,cpp}` |
| `bridge/` | HTTP front end for synapd, plus its user service |
| `chiron.ini` | Runtime config, installed into the game folder |
| `patch-imports.py` | Import-table redirect, with `--restore` |
| `install.sh` | Build output → game folder, bridge service, import patch |

## Credits

Thinker Mod by Induktio (MIT). Scient's Unofficial Patch by Brendan Casey.
Alpha Centauri © Firaxis Games / Electronic Arts.
