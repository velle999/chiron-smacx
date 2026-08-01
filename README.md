# Chiron Rising — a mod pack for Alpha Centauri

Faction leaders in SMACX speak lines written on the spot by a local model,
instead of the canned strings in `Script.txt` — 503 of its blocks are rewritten,
and a leader asked the same thing twice does not answer the same way. Built on
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

**Two repos make this mod.** This one is the pack — installer, bridge, config,
docs. The DLL source is
[**velle999/thinker-chiron**](https://github.com/velle999/thinker-chiron/tree/chiron)
(branch `chiron`), a fork of Thinker that keeps upstream history so it can rebase
onto induktio. It is deliberately *not* a submodule; clone it inside this one.

## Quickstart

You need a Linux box with Alpha Centauri: Alien Crossfire (v2.0), a local model
served by [synapd](https://github.com/velle999/SYNAPSE), `llama-server` or
`ollama`, and — if you are building rather than unpacking a release — an
**msvcrt** cross-compiler.

```bash
# 1. get both repos
git clone https://github.com/velle999/chiron-smacx
git clone -b chiron https://github.com/velle999/thinker-chiron \
    chiron-smacx/thinker-chiron
cd chiron-smacx

# 2. build the DLL  -- see "From source" below for the configure + build pair.
#    Skip this entirely if you unpacked a release zip.
#    The compiler is the one thing that bites: it MUST be msvcrt, not UCRT.

# 3. install into the game folder, start the bridge, patch the import table
./install.sh

# 4. play
#    launch Alpha Centauri from Steam as usual
```

`install.sh` finds a Steam install by default; point it elsewhere with
`GAME=/path/to/game ./install.sh`. It backs up everything it touches to
`<game>/_vanilla_backup/`, so uninstalling is `patch-imports.py --restore` plus
putting those files back.

**Check it loaded:** `Ctrl+F4` shows the mod version. If it does not, the DLL
never loaded and nothing below applies — go to
[Troubleshooting](#troubleshooting).

| Key | |
|---|---|
| `Ctrl+F4` | Mod version — the one-second check that Chiron is live |
| `Alt+T` | Thinker's options |
| `Alt+N` | **Planetnet dispatch** — what changed since you last looked |

## What the mod adds

Five things, all of which fall back silently to stock behaviour if the bridge is
down or a reply is unusable. There is no failure mode where a dialogue box comes
up empty.

| | |
|---|---|
| **Diplomacy** | 503 speech blocks rewritten in character at read time, so a leader asked the same thing twice does not answer the same way |
| **Leader memory** | What leaders say follows from what has actually passed between you — the wars, the broken promises, the debts. See [Leader memory](#leader-memory) |
| **Base names** | New bases are named from the faction's own culture instead of a fixed list of 75. See [Base names](#base-names) |
| **Planetnet** | `Alt+N` — an in-fiction wire dispatch on what changed since the last bulletin. See [Planetnet](#planetnet) |
| **Probe protests** | Object when a faction runs probe teams against you, instead of choosing between robbery and war. See [Probe protests](#probe-protests) |

## What this does and does not change

The engine's logic is untouched. The same demand is made, the same buttons
appear, the same treaty is signed or refused. Only the **wording** changes, and
only where a leader is speaking.

That is decided structurally, not from a list of labels. A speech block opens
with control lines (`#xs`, `#caption`) and quoted prose; a menu has neither and
is one option per line. Across `Script.txt`'s 1572 blocks that comes to **503
rewritten and 107 menus left alone** — `#DEMANDTECH11` is Lal talking,
`#DEMANDTECH11A` is the four answers you pick from, and rewriting the second
would leave a demand with no way to reply.

> An earlier version matched 25 label prefixes and reached 84 of the 468
> quoted-speech blocks. Most of what a leader said stayed vanilla, so the mod
> looked dead while working perfectly.

> Chiron Rising's *rules* — the social engineering table, the tech tree, the
> seven faction bonuses — are byte-for-byte vanilla SMAC. Porting them into
> `alphax.txt` would recreate the stock game, so this pack deliberately ships
> none of it. The dialogue layer is the part that was actually original.

All **fourteen** faction leaders have character bibles: the seven original SMAC
leaders, plus the Alien Crossfire seven — Consciousness, Pirates, Free Drones,
Data Angels, Cult of Planet, Caretakers and Usurpers. Their titles, adjectives,
agendas and accusations are taken from each faction's own `.txt` in the game
folder, so a generated line matches what the engine already says about them.

> A leader with no bible falls back to vanilla dialogue silently, which is
> indistinguishable from the mod not being installed. If speech looks canned,
> check `chiron_trace.txt` for a `hook: rewriting …` line before assuming the
> mod is broken.

## How it works

```
                                                        ┌─> synapd    (unix socket)
terranx.exe ──imports──> thinker.dll ──HTTP──> chiron-bridge ─> llama-server :8080
                                                        └─> ollama    :11434
```

The bridge tries those in order, or one named with `--backend`. Only the first
needs SynapseOS; the other two need nothing but a listening port, which is what
makes the pack runnable anywhere.

`text_open()` is the single funnel every labelled text block in the game passes
through. Once the engine has seeked to a `#LABEL`, Chiron reads the vanilla
block, writes the rewrite to `chiron_gen.txt`, and calls the engine's *own*
`text_open()` on that file. `text_get()` keeps `fgets()`ing lines and never
knows.

> **The engine has to open that file itself.** `terranx.exe` imports no C
> runtime — it statically links MSVC 6's LIBC, with its own `_iob`, its own
> descriptor table and its own heap. Handing it a `FILE*` opened by the DLL
> appears to work, because the game reads the first lines out of a buffer that
> is already filled; then `_cnt` runs out, its own `_filbuf` calls `_read()`
> with our descriptor against *its* table, and the game dies on a foreign handle
> with `STATUS_ACCESS_DENIED`. The struct layout does match msvcrt, which is
> what makes this so convincing. No `FILE*` may cross that boundary in either
> direction.

**Nothing can come up blank.** A dead bridge, a slow model, an empty reply, or a
reply that lost a placeholder all mean "show the line the game shipped".

### Placeholders

Vanilla lines contain `$TOKEN`s the engine substitutes after load — `$TECH0` is
the tech being demanded, `$NUM0` the credits offered. Losing one would leave you
agreeing to a blank, so:

- **Only data-carrying tokens are mandatory** — `TECH`, `NUM`, `ENERGY`,
  `CREDIT`, `BASENAME`, `PROJECT`, `UNITTYPE`. A reply that drops one is
  discarded.
- **Everything else is cosmetic**, including `$NAME` and `$TITLE`. This is an
  allowlist, so an unrecognised token keeps the generation rather than binning
  it.
- **Invented tokens are scrubbed.** The engine renders an unrecognised token
  literally, so a hallucinated `$HONORED_ONE` would be visible junk.
- **Conditionals are flattened before the model sees them.**
  `$<2:his:her:x:x>` picks a pronoun from a faction's gender and
  `$<M2:$FACTIONPEJ3>` gates a token. Shown that syntax, a 7B copies it and gets
  it wrong — one reply shipped `<M2:>`, which the engine printed as junk.

> Getting this backwards is expensive. With everything except `$TITLE`
> mandatory, `$NAME` — which appears in **290 of the 503** blocks — sent nearly
> every generation to the bin: the model writes the person's name instead of
> echoing the placeholder, so a perfectly good line was discarded and the
> vanilla one shown, identically, every single visit. Losing `$NAME` costs an
> honorific. Losing `$TECH0` leaves you agreeing to a blank.

## Leader memory

A leader who lost two bases to you last turn used to open exactly like one you
had never met. Every prompt now carries what has actually passed between the two
of you, and it changes what they say:

| History | Santiago, on the same tech demand |
|---|---|
| first meeting | *"Give me your intel on that tech, or face my wrath."* |
| long grudge | *"Your betrayals and thefts have left a bitter taste."* |
| old allies | *"Or face my wrath, and the debt you owe."* |

**None of this is recorded by the mod.** The engine already keeps the whole
per-pair relationship in its `Faction` struct and writes it into the save —
treaties and vendettas, broken promises counted in both directions, the turn you
last spoke, stolen research, mind control, gifts, loan balances, power ranking.
`build_dossier()` reads it at prompt time, so it cannot drift out of sync with
the game and it survives save/load with no save format of ours.

The rule asks for tone before recital. Told plainly to *use* the history, a small
model opens every line with a grievance inventory; what makes a leader feel like
they remember is that a betrayal soured how they greet you. At a first meeting no
history is offered and none is invented.

## Base names

Every game drew the same 75 names from `basenames/gaians.txt` in much the same
order, and a wide empire ran the list out and fell through to `Sector 14`. Bases
are now named from the faction's own culture — `Mycelial Haven` for the Gaians,
`Redemption's Ridge` for the Believers, `Valor Vanguard` for the Spartans.

Names are generated **a dozen at a time** and drawn from a pool, because base
founding is not a dialogue box: the AI factions do it throughout turn
processing, and a two-second stall on each would read as the turn hanging. One
call per twelve bases puts the whole-game cost at a handful of pauses. One
failure latches that faction's pool for the session rather than retrying at
every founding.

The prompt shows the faction's **own shipped names** as the house style, which
is the entire difference between this working and not. Described only in prose,
the model reached for the vocabulary of the creed and welded it together — the
Hive returned `CollectiveCold`, `IllusionRelease`, `PainFreedom`. Its real list
says `Collective Bastion`, `Communal Hub`. Six of those in the prompt fixed it
outright.

Set `base_names=0` in `chiron.ini` to restore the vanilla lists.

## Planetnet

`Alt+N` in the map window writes an in-fiction wire dispatch on the state of
Planet. It is the only feature here with no vanilla text behind it, and so the
only one you ask for rather than one that happens to you — which is also why a
two-second wait is acceptable where the same pause mid-turn would not be.

> The Human Hive, our most aggressive neighbor, declared war on The Peacekeeping
> Forces. The Hive's expansion continues, with two new bases founded. The Spartan
> Federation, meanwhile, lost a base. The Human Hive was condemned for a major
> atrocity, but details remain scarce.

**News is what changed, and a snapshot is not news.** Handed the current
standings, the model transcribed the table and then padded to the token ceiling
with invention — losses nobody took, a famine nobody suffered, a war between two
factions who were not at war. That is not the model misbehaving: a snapshot
contains no events, so asking for a report of events leaves it nothing to write
and every reason to make some up. Chiron keeps the previous bulletin's numbers
and reports the **diff** — bases gained and lost, wars declared and ended, pacts
signed, atrocities condemned, factions eliminated.

When nothing has changed the model is not called at all; you get *"No
developments since the last bulletin."* Asked to report a quiet turn it invented
a base count that was never true.

> Rendered through a `#CHIRONNEWS` block in `modmenu.txt` — one more reason that
> file has to be the copy `install.sh` ships.

## Probe protests

The game exempts probe teams from diplomacy. A faction you are not at war with
can strip your labs every few turns, and your only answers are to accept it or
declare war — which usually costs more than the research did.

Now a theft is noticed at the start of your turn and you can demand they stop.
They answer in character, and if they agree **their probe teams actually leave
you alone** for 30 turns.

> *"Your research is valuable. But my soldiers' lives are more so. I will not
> risk them for it. I am a warrior, not a thief. I respect your strength. I will
> call my teams off."* — Santiago, agreeing
>
> *"Our treaty does not grant you the right to dictate our actions. We will not
> abandon our pursuit of knowledge."* — Lal, refusing

**Chiron decides the words, never the outcome.** Whether they back down is
settled from faction state on the same terms the engine uses — what standing
they would forfeit, and whether your power ranking makes the threat credible. The
model is only asked to say it in character. A leader who agreed and then went on
stealing would be worse than never offering the conversation.

What you can threaten scales with standing: a pact partner risks the pact, a
treaty partner the treaty, and with nothing formal between you only strength
talks — so an unbound faction that outranks you will simply refuse. A refusal is
remembered and colours later dialogue. A vendetta cancels any promise outright.

> Worth knowing, because it revises the usual complaint: the engine's own gate
> checks `DIPLO_PACT` and **not** `DIPLO_TREATY`. An AI pact partner already
> declines to probe you unless the probe was waypointed onto the base — it is
> **treaty** partners that help themselves freely.

The warning is stored in a block of `MFaction` the engine already saves, so it
survives save/load with no save format of ours, and `sizeof(MFaction) == 1436`
still holds. Set `probe_protests=0` in `chiron.ini` to turn the whole thing off.

## Install

### From a release zip

Unpack it into the game folder and run `install.sh`. No compiler needed.

### From source

The DLL source lives in a separate repo — clone it alongside this one:

```bash
git clone https://github.com/velle999/chiron-smacx
git clone -b chiron https://github.com/velle999/thinker-chiron chiron-smacx/thinker-chiron
cd chiron-smacx
```


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

PATH="$HOME/toolchains/bin14:$PATH" \
  cmake --build thinker-chiron/build/gcc14 --target thinkerlib -j"$(nproc)"

i686-w64-mingw32-objdump -p thinker-chiron/build/gcc14/thinker.dll | grep 'DLL Name'
./install.sh
```

Three things about that build line, each of which has produced a UCRT DLL that
looked fine:

- **`bin14` must be on `PATH`.** CMake links with a *bare*
  `i686-w64-mingw32-g++`, not the absolute `CMAKE_CXX_COMPILER` above, so
  without it the link resolves to the distro's UCRT driver. `CMakeCache.txt`
  still names the right compiler and still says
  `MOD_CRT_IS_MSVCRT:INTERNAL=1` — **the cache is not evidence.**
- **Always re-check the import table.** It must list `msvcrt.dll` and no
  `api-ms-win-crt-*`. That objdump line is the only real check.
- **`--target thinkerlib`.** `thinker.exe` fails to link on `_imp___vsnprintf`
  and is not used — the install redirects an import instead of using the
  launcher. And `cmake --build` will happily print "Built target" without
  relinking; `rm -f thinker.dll` first if you need to be sure.

Configure must also report `MOD_CRT_IS_MSVCRT - Success`. If it warns instead,
stop and fix the toolchain — the build will compile and link cleanly and then
fail at startup.

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
falls off the edge — "EXIT GAME" and the copyright line disappear.

**Force the window fullscreen from the compositor** rather than shrinking the
game — on synui that is `Super+Shift+F`. Keep the game at the monitor's real
resolution; a fullscreen window covers the panel and nothing is clipped.

Shrinking to fit the panel is the fallback if your compositor cannot force
fullscreen. Subtract the exclusive zone and round **down** to a multiple of 8 —
`2560x1440` minus a 28px panel is `1412`, and `1412 % 8 = 4`, so `1408`. Leaving
it at 1412 trips the divisibility rule and the game dies with the draw-buffer
error instead of merely looking wrong.

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

### Every leader says the same canned line

Usually the mod is working and the backend is dead. Vanilla reuses one block per
label, so all seven factions delivering an identical demand is the signature of
the fallback path doing its job.

**Rejections are logged to `chiron.txt`, not `chiron_trace.txt`.** A trace that
shows `bridge returned 1` with no `engine reopened` after it means generation
succeeded and the result was then thrown away — and only `chiron.txt` says why:

```
http: non-200 response: HTTP/1.1 502 Bad Gateway
[DEMANDTECH11] generation failed, using vanilla
[BETRAYFRIEND] dropped placeholder $NAME0, using vanilla
```

The second line is a live backend and an over-strict placeholder rule. See
[Placeholders](#placeholders).

`curl -s localhost:11436/health` reports every backend at once, so "which of
these is actually up" is one command:

```json
{"ok": true, "using": "synapd",
 "backends": {"synapd": "/run/synapd/synapd.sock",
              "llamacpp": "down (Connection refused)",
              "ollama": "down (Connection refused)"}}
```

**On a desktop that manages the GPU, suspect its game mode first.** synui detects
a fullscreen XWayland window as a game and runs

```
sudo -n systemctl stop synapd.socket synapd.service
```

to free ~4GB of VRAM. That is correct for a modern title and exactly wrong here:
launching SMACX kills the model the mod needs, so every line falls back to
vanilla for the whole session. The journal shows synapd starting and taking
SIGTERM in the same second.

Fix it by excluding the game from detection, in `~/.config/synui/synuirc` —
the list replaces the built-in default, so repeat the stock entries:

```
game_exclude = firefox chibi tepris nexus-chat foot steam_app_2204130
```

`Super+G` cycles auto → forced-on → forced-off → auto for the current session.
A 1999 game does not want the VRAM, so there is nothing to trade away.

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
| `winsock: ready=…` | networking is up |
| `lookup: FILE / LABEL` | every block the engine asked for |
| `hook: rewriting …` | recognised as a leader speaking |
| `rw: … calling bridge` | prompt built, waiting on the model |
| `rw: engine reopened …` | the rewrite is installed — this is success |

A `hook: rewriting` with no `engine reopened` after it means the reply was
generated and rejected; `chiron.txt` has the reason.

### Crash codes

The two the mod itself has caused, both distinctive:

| Code | Meaning |
|---|---|
| `c0000022` — access **denied**, in ntdll | A `FILE*` crossed the CRT boundary. See [How it works](#how-it-works) |
| `c0000005` at an **ASCII-looking address** | A buffer overflow, not a bad pointer. `73657669` is `"ives"` — the engine jumped into text |

The second came from feeding the engine a 300-character line. Every line in the
shipped scripts is hand-wrapped and the longest is 106 characters, so generated
prose is wrapped at 68 columns before it is written.

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

`chiron.ini`, installed into the game folder.

| Key | |
|---|---|
| `enabled` | `0` restores stock Thinker completely |
| `base_names` | `0` restores the vanilla `basenames/` lists |
| `probe_protests` | `0` disables objecting to probe operations |
| `max_tokens` | Reply length against the in-game pause. **110** is a paragraph |
| `timeout_ms` | Give up and use vanilla text after this |
| `host`, `port` | Where the bridge is listening |
| `debug` | `1` writes `chiron.txt`: every label, whether it was rewritten, and why anything was rejected |

> `max_tokens` in the ini **overrides** the default compiled into the DLL, so
> editing the C constant alone does nothing. It shipped at 320 once, which gave
> a repeating leader enough room to say the same thing seven times and still be
> cut off mid-word.

The bridge itself takes `--backend auto|synapd|llamacpp|ollama`,
`--llamacpp-url`, `--ollama-url`, `--ollama-model` and `--temperature`. `auto`
probes cheaply and only tries to *start* synapd once nothing at all answers —
doing that first cost 25 seconds per line on machines that simply do not have
it.

## Tuning the writing

Quality comes mostly from the prompt; `src/chiron.cpp`'s `build_prompt()` is
where to iterate. Judge output without launching the game by posting a prompt
straight at the bridge:

**Put the rule that must hold at the very end.** This came up three separate
times and cost real debugging each time — the close of the prompt is what a
small model weighs most.

- The variation counter shipped as the last line, `- Phrasing 3: word it
  differently than before.` A numbered item closing a bullet list is the
  strongest possible cue to write another one, and Santiago duly opened a popup
  with `- Phrasing 2: use a metaphor.` followed by three labelled alternative
  greetings.
- Moving the mandatory-placeholder reminder from the middle of the rules to the
  last line before the answer cue took `$TECH0` retention from 9/12 to 11/12.
  Every drop is a whole generation discarded for vanilla.
- Planetnet's "invent nothing" rule sits alone at the end for the same reason.

Corollary: end on a cue to *speak*, not on a rule. Chiron's prompts close with
`MESSAGE IN YOUR VOICE:` and `DISPATCH:`.


```bash
curl -s localhost:11436/generate -H 'Content-Type: application/json' \
  -d '{"prompt":"...","max_tokens":110}' | python3 -m json.tool
```

### The pause before a leader speaks

Generation is synchronous — the game is blocked while the model writes. Measured
against a 7B/q4 fully offloaded to a 12GB card:

| | |
|---|---|
| generation | **~60 tok/s**, flat regardless of context length |
| prompt evaluation | **~1900 tok/s** |

So a 550-token prompt costs ~0.3s and 110 generated tokens cost ~1.8s.
**`max_tokens` is the lever; prompt length barely matters** — trimming the
persona buys about a tenth of a second and costs character. Drop `max_tokens` in
`chiron.ini` to ~70 for roughly 1.2s per line, at the price of shorter replies.
No rebuild needed.

### Leaders repeating themselves

If the same leader greets you with the same sentence every visit, the backend is
sampling greedily: an identical prompt returns a byte-identical reply. Chiron
puts the mission year, turn and a counter into every prompt so the text differs
anyway, but the real fix is on the backend.

- `llama-server` and `ollama` take `--temperature` from the bridge (default 0.8).
- `synapd` needs **0.1.0-22 or newer**; before that its sampler was hardcoded
  greedy and its wire protocol carried no temperature at all. `synapd
  --temperature 0` restores the deterministic behaviour.

Greedy decoding does not just repeat between visits — it loops *inside* one
reply, because a model with no repetition penalty will keep writing a sentence
it likes. Lal once restated the same commendation seven times in a single popup
and still ran out of room mid-word. Sampling is not the mod's to fix, so
`tidy_reply()` trims what arrives: everything from a bullet or an ALL-CAPS label
onwards, then duplicate sentences and anything past four, then a trailing
fragment with no terminator. It also normalises the quoting to the one pair per
block that every shipped speech block uses.

## Layout

| Path | |
|---|---|
| [`thinker-chiron/`](https://github.com/velle999/thinker-chiron/tree/chiron) | Thinker fork, `chiron` branch — separate repo, keeps upstream history so it can rebase onto induktio. All new code in `src/chiron.{h,cpp}` |
| `ab.sh` | Swap the installed DLL for single-variable launch tests |
| `package.sh` | Build a distributable zip needing no compiler |
| `docs/toolchain.md` | Why the compiler matters, and a root-free GCC 14 setup |
| `bridge/` | HTTP front end — synapd, llama.cpp or ollama — plus its user service |
| `chiron.ini` | Runtime config, installed into the game folder |
| `patch-imports.py` | Import-table redirect, with `--restore` |
| `install.sh` | Build output → game folder, bridge service, import patch |

## Credits

Thinker Mod by Induktio (MIT). Scient's Unofficial Patch by Brendan Casey.
Alpha Centauri © Firaxis Games / Electronic Arts.
