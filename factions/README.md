# Chiron factions

Two new playable factions for SMACX. `install.sh` copies them into the game
folder — but **copying them in is not enough to see them.**

## The roster is seven fixed slots in the ini

There is no directory scan. `prefs_fac_load()` (`src/config.cpp:1686`) reads
`Alpha Centauri.Ini` when `Prefs Format=12` and loops `Faction 1` … `Faction 7`,
taking each faction's *filename* from the ini:

```ini
[Alpha Centauri]
Prefs Format=12
Faction 1=CYBORG
Faction 2=PIRATES
...
Faction 7=USURPER
```

`MaxPlayerNum` is 8, so there are exactly seven slots and **a new faction has to
displace one.** Installing the files and expecting them to appear is the failure
mode this note exists to prevent — nothing errors, the picker simply shows the
seven factions the ini names.

To use these, edit two of those lines to `SUFFIC` and `ORACLE`. The vanilla ini
is preserved in `_vanilla_backup/`.

```
SUFFIC.TXT            Kaya's Sufficiency  — the degrowth argument
ORACLE.TXT            The Cassandra Directorate — the information argument
basenames/*.txt       expanded base-name pools (Chiron few-shots from these)
validate.py           structural check against the shipped faction files
```

## Why these two

Each faction in SMAC is an argument. The unfilled slots are where mods live —
but "unfilled" has to be measured against the files, not against memory. Both
of these started adjacent to something that already ships, and moved:

| First idea | What already occupies it | Where it moved |
|---|---|---|
| native-life degrowth faction | **Cult of Planet** is already `++PLANET -INDUSTRY -ECONOMY` with a Wealth aversion | eudaimonia instead of native life — `IMPUNITY, Eudaimonic`, which no faction uses |
| probe/espionage specialist | **Data Angels** are `++PROBE, PROBECOST 75, TECHSHARE 3`; **University** is the exact inverse (`++RESEARCH --PROBE`) | not stealing secrets — knowing anyway, and being disbelieved for it |

## The constraint that shaped both

**SMAC has no diplomacy stat.** `#SOCIO` defines exactly eleven effects —
ECONOMY, EFFIC, SUPPORT, TALENT, MORALE, POLICE, GROWTH, PLANET, PROBE,
INDUSTRY, RESEARCH — and `FACTION.TXT`'s rule vocabulary has no trust knob.
A "diplomacy penalty" is therefore only half expressible in vanilla:

- `VOTES, 0` locks the Directorate out of the Council (Peacekeepers ship
  `VOTES, 2`, so the multiplier is live).
- The rest — *being right and disbelieved* — lives in the Chiron persona in
  `src/chiron.cpp`, because the dialogue is generated. That faction could not
  have existed in 1999.

## Mechanics claimed

Three keywords were unused by all fourteen shipped factions, and two of them
are load-bearing here:

| Keyword | Vanilla users | Used by |
|---|---|---|
| `IMPUNITY` | Cyborg only (`Cybernetic`) | Sufficiency (`Eudaimonic`) |
| `PENALTY` | **none** | Sufficiency (`Free Market`) |
| `COMMFREQ` | **none** | Directorate |

`PENALTY, Free Market` is how "no Free Market" gets said. The engine has no ban
keyword — Morgan's inability to run Planned is hardcoded, not declared — so
doubling the penalty is the honest version, and it matches how the game already
handles ideological distaste through aversions rather than prohibitions.

## Validating a change

The header block is parsed **positionally**. The rhetoric strings are found by
their offset from the stat line, not by any label, so a file one line short
parses every string one slot early and the faction talks nonsense with no error
anywhere.

```sh
./validate.py SUFFIC.TXT ORACLE.TXT
```

It compares against `GAIANS.TXT` in the installed game (override with `GAME=`),
and it passes on `PEACE.TXT`, `angels.txt` and `hive.txt` — so a pass means
something.

## `<faction>.pcx` is a SPRITE ATLAS, not a portrait

This one cost a play session. Open `Gaians.pcx` and it is labelled inside the
image: **LAND BASES, SEA BASES, WATER BASES**, leader thumbnails, the insignia
at several sizes, and colour swatches for `Faction Color`, `Faction Text
Color`, `Border Color` and `Vehicle Color`, all over a magenta transparency
key. Every region has to sit where the engine expects it.

Writing flat art into that slot produces a faction whose **bases render as
nothing at all** — no error, the tiles are simply empty.

So a new faction inherits a stock atlas and gets repainted; it cannot be drawn
from scratch without the region map:

```sh
art/make_art.py suffic --donor GAIANS   # atlas + .flc
art/make_art.py oracle --donor UNIV
```

**The donor also sets the faction's in-game colour**, so pick one that is not
in the active roster or two factions share a colour. `2.pcx` and `3.pcx` are
ordinary art and stay ours.

| File | What it is |
|---|---|
| `<stem>.pcx` | **sprite atlas** — bases, thumbnails, insignia, colour key |
| `<stem>2.pcx` | 200×120 small portrait |
| `<stem>3.pcx` | 1024×768 insignia / lineup art |
| `<stem>.flc` | leader animation |
| `voices/<stem>.mp3` | the pick-screen speech |

## Voices

The stock factions read their blurb aloud when you pick them; custom factions
never have (BRIAN and SID, the base game's own hidden factions, ship no mp3).
The filename is keyed on the stem, so supplying the file is all it takes.

```sh
voice/make_voice.py suffic --factions .. --install "$GAME"
```

Text comes from the faction file's own `#BLURB` — the same passage the stock
voices read — with the `^` attribution lines dropped. Piper lives inside the
`chibi` package rather than on PATH, and there is one installed voice, so the
two leaders are separated by pitch and tempo rather than by model. Output is
mp3 / 22050 Hz / mono / 64 kbps, matching every shipped file exactly.

## Not done

- **`VOTES, 0` is unverified.** Zero may read as "no votes" or as "unset". If
  the Council misbehaves, `VOTES, 1` is the safe fallback and costs only
  flavour.
- The atlases are donor art. Bases, units and colours are Gaian and University
  until someone repaints the regions.
