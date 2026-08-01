# Chiron factions

Two new playable factions for SMACX. `install.sh` copies them into the game
folder; the faction picker reads the directory, so **a faction is installed by
being present** — there is no list to register it in.

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

## Not done

- **No artwork.** A faction wants `<name>.pcx` (1024×768 leader portrait),
  `<name>2.pcx` (200×120), `<name>3.pcx` (1024×768) and optionally `.flc` and
  `voices/<name>.mp3`. Untested how the game behaves with these absent.
- **`VOTES, 0` is unverified.** Zero may read as "no votes" or as "unset". If
  the Council misbehaves, `VOTES, 1` is the safe fallback and costs only
  flavour.
- Neither faction has been loaded in-game.
