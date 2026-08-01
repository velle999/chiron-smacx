# Chiron Rising — a mod pack for Alpha Centauri

Faction leaders in SMACX speak lines written on the spot by a local model,
instead of the ~1500 canned strings in `xscript.txt`. Built on
[Thinker](https://github.com/induktio/thinker) v5.4, which also carries
[Scient's Unofficial Patch](https://github.com/DrazharLn/scient-unofficial-smacx-patch)
v2.0.

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

```bash
cd thinker-chiron && cmake --preset release && cmake --build --preset release
cd .. && ./install.sh
```

Needs `mingw-w64-gcc` (`i686-w64-mingw32-g++`). The installer backs up anything
it overwrites to `<game>/_vanilla_backup/`, keeps `terranx.exe.vanilla`, and
enables the bridge as a user service.

Then launch from Steam normally. `Ctrl+F4` shows the mod version; `Alt+T` opens
Thinker's options. If neither shows the mod, it did not load.

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
