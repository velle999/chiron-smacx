<#
.SYNOPSIS
    Install the Chiron Rising mod pack over an existing SMACX install, on Windows.

.DESCRIPTION
    The Windows counterpart to install.sh. Same steps, same guards, same
    reversibility: Thinker never writes to terranx.exe, and anything this
    overwrites is copied to _vanilla_backup\ first.

    Two things differ from the Linux install, and both are because of the
    platform rather than the mod:

      * There is no systemd, so the bridge is not enabled as a service. This
        writes start-bridge.cmd next to the script and can register a logon task
        with -InstallBridgeTask.
      * synapd is SynapseOS-only and its socket does not exist here. With
        -Backend ollama (the default) the DLL talks to ollama directly and
        there is no bridge process at all, which is the point: ollama already
        runs as a service on Windows, so nothing extra has to be kept alive.

    UNTESTED ON WINDOWS. It is written from the Linux installer and the game's
    file layout; the author develops on Linux with Steam/Proton. If it goes
    wrong, everything it touched is in _vanilla_backup\ and terranx.exe.vanilla.

.PARAMETER Game
    Path to the Alpha Centauri folder. Probed from the usual Steam and GOG
    locations when omitted.

.PARAMETER Backend
    Where the mod gets its text. 'ollama' (default) and 'llamacpp' talk to
    those servers directly and need no bridge process. 'bridge' runs
    chiron-bridge, which adds a fallback chain but has to be kept running --
    there is no systemd here, so that is a manual step or a Scheduled Task.
    synapd is deliberately not offered; it does not run on Windows.

.PARAMETER InstallBridgeTask
    Only meaningful with -Backend bridge: register a Scheduled Task that starts
    the bridge at logon.

.PARAMETER Restore
    Undo: put back the vanilla terranx.exe and the files in _vanilla_backup\.

.EXAMPLE
    .\install.ps1
.EXAMPLE
    .\install.ps1 -Game "D:\Games\Alpha Centauri" -Model mistral
.EXAMPLE
    .\install.ps1 -Backend bridge -InstallBridgeTask
.EXAMPLE
    .\install.ps1 -Restore
#>
[CmdletBinding()]
param(
    [string]$Game,
    [ValidateSet('ollama', 'llamacpp', 'bridge')]
    [string]$Backend = 'ollama',
    [string]$Model = 'llama3.2',
    [switch]$InstallBridgeTask,
    [switch]$Restore
)

$ErrorActionPreference = 'Stop'
$Src = $PSScriptRoot

function Fail($msg) { Write-Host "error: $msg" -ForegroundColor Red; exit 1 }
function Note($msg) { Write-Host $msg }
function Warn($msg) { Write-Host $msg -ForegroundColor Yellow }

# ── locate the game ────────────────────────────────────────────────────────
if (-not $Game) {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Steam\steamapps\common\Sid Meier's Alpha Centauri",
        "$env:ProgramFiles\Steam\steamapps\common\Sid Meier's Alpha Centauri",
        "${env:ProgramFiles(x86)}\GOG Galaxy\Games\Sid Meier's Alpha Centauri",
        "$env:ProgramFiles\GOG Galaxy\Games\Sid Meier's Alpha Centauri",
        "C:\GOG Games\Sid Meier's Alpha Centauri"
    )
    # Steam libraries are frequently on another drive; read the folder list.
    $vdf = "${env:ProgramFiles(x86)}\Steam\steamapps\libraryfolders.vdf"
    if (Test-Path $vdf) {
        Select-String -Path $vdf -Pattern '"path"\s+"(.+?)"' | ForEach-Object {
            $lib = $_.Matches[0].Groups[1].Value -replace '\\\\', '\'
            $candidates += "$lib\steamapps\common\Sid Meier's Alpha Centauri"
        }
    }
    $Game = $candidates | Where-Object { Test-Path (Join-Path $_ 'terranx.exe') } |
            Select-Object -First 1
}
if (-not $Game -or -not (Test-Path (Join-Path $Game 'terranx.exe'))) {
    Fail "no terranx.exe found. Pass -Game 'C:\path\to\Alpha Centauri'"
}
Note "game: $Game"

# ── restore ────────────────────────────────────────────────────────────────
if ($Restore) {
    $py = Get-Command python, python3, py -ErrorAction SilentlyContinue |
          Select-Object -First 1
    if ($py) {
        & $py.Source (Join-Path $Src 'patch-imports.py') `
            (Join-Path $Game 'terranx.exe') '--restore'
    } else {
        Warn "python not found; restore terranx.exe from terranx.exe.vanilla yourself"
    }
    $backup = Join-Path $Game '_vanilla_backup'
    if (Test-Path $backup) {
        Get-ChildItem $backup -File | ForEach-Object {
            Copy-Item $_.FullName (Join-Path $Game $_.Name) -Force
            Note "restored $($_.Name)"
        }
    }
    Remove-Item (Join-Path $Game 'thinker.dll') -ErrorAction SilentlyContinue
    Note 'restored. Steam file verification also undoes the import patch.'
    exit 0
}

# ── prerequisites ──────────────────────────────────────────────────────────
$python = Get-Command python, python3, py -ErrorAction SilentlyContinue |
          Select-Object -First 1
if (-not $python) {
    Fail "python not found on PATH. It is needed to patch the import table and to run the bridge. Install it from python.org or the Microsoft Store."
}

$build = Join-Path $Src 'thinker-chiron\build\gcc14'
if (-not (Test-Path (Join-Path $build 'thinker.dll'))) {
    $build = Join-Path $Src 'thinker-chiron\build\release'
}
if (-not (Test-Path (Join-Path $build 'thinker.dll'))) {
    # A release zip unpacks the DLL beside this script.
    if (Test-Path (Join-Path $Src 'thinker.dll')) { $build = $Src }
}
if (-not (Test-Path (Join-Path $build 'thinker.dll'))) {
    Fail "no thinker.dll found. Unpack a release zip here, or build one -- see README, From source."
}
Note "dll:  $build\thinker.dll"

<#
SMAC's Buffer_copy crashes on window dimensions that are not multiples of 8, and
the only symptom is "unable to allocate draw buffer, terminating program" -- no
log line, nothing pointing at the resolution. Same guard as install.sh.
#>
$ini = Join-Path $Game 'thinker.ini'
if (Test-Path $ini) {
    foreach ($name in 'width', 'height') {
        $m = Select-String -Path $ini -Pattern "^window_$name=(\d+)" |
             Select-Object -Last 1
        if ($m) {
            $val = [int]$m.Matches[0].Groups[1].Value
            if ($val % 8 -ne 0) {
                Fail "thinker.ini window_$name=$val is not a multiple of 8. The game will die with 'unable to allocate draw buffer'."
            }
        }
    }
}

# ── back up anything we are about to overwrite ─────────────────────────────
$backup = Join-Path $Game '_vanilla_backup'
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach ($f in 'alphax.txt', 'tutor.txt', 'helpx.txt', 'conceptsx.txt',
                'modmenu.txt', 'Alpha Centauri.Ini') {
    $from = Join-Path $Game $f
    $to   = Join-Path $backup $f
    if ((Test-Path $from) -and -not (Test-Path $to)) {
        Copy-Item $from $to
        Note "backed up $f"
    }
}

<#
Thinker's data files are part of the build, not optional extras. The DLL asks
modmenu.txt for labels by name and a version predating the code silently has
none of them -- and Chiron adds #CHIRONNEWS and #CHIRONPROBE on top, so an old
modmenu.txt breaks the dispatch and the probe protest as well.

thinker.ini is deliberately NOT overwritten: it holds the user's video settings.
#>
$docs = Join-Path $Src 'thinker-chiron\docs'
foreach ($f in 'modmenu.txt', 'alphax.txt') {
    $from = Join-Path $docs $f
    if (Test-Path $from) {
        Copy-Item $from (Join-Path $Game $f) -Force
        Note "installed $f (Thinker's, matching the DLL)"
    }
}
foreach ($d in 'basenames', 'smac_mod', 'german') {
    $from = Join-Path $docs $d
    if (Test-Path $from) {
        $dest = Join-Path $Game $d
        New-Item -ItemType Directory -Path $dest -Force | Out-Null
        Copy-Item "$from\*.txt" $dest -Force -ErrorAction SilentlyContinue
    }
}

Copy-Item (Join-Path $build 'thinker.dll') (Join-Path $Game 'thinker.dll') -Force

<#
chiron.ini is rewritten rather than copied, so the backend picked above is the
one the DLL actually uses. Everything else in the shipped file is kept.
#>
$port = @{ ollama = 11434; llamacpp = 8080; bridge = 11436 }[$Backend]
(Get-Content (Join-Path $Src 'chiron.ini')) |
    ForEach-Object {
        $_ -replace '^backend=.*', "backend=$Backend" `
           -replace '^model=.*',   "model=$Model" `
           -replace '^port=.*',    "port=$port"
    } | Set-Content -Path (Join-Path $Game 'chiron.ini') -Encoding ASCII
Note "installed thinker.dll (chiron build), chiron.ini (backend=$Backend, port=$port)"

# ── import-table redirect ──────────────────────────────────────────────────
# Makes terranx.exe load the DLL by itself, so the Play button is the launcher.
# Keeps terranx.exe.vanilla; undone by -Restore or Steam's file verification.
& $python.Source (Join-Path $Src 'patch-imports.py') (Join-Path $Game 'terranx.exe')
if ($LASTEXITCODE -ne 0) { Fail "patch-imports.py failed" }

# ── the bridge ─────────────────────────────────────────────────────────────
<#
No systemd here, so the bridge does not become a service. Without it running,
the mod silently shows the game's original dialogue -- which is a working game,
just not a modded one.

synapd is not offered: it is SynapseOS-only and speaks over a unix socket that
does not exist on Windows. Naming a backend explicitly also saves the bridge a
failed probe on every single request.
#>
if ($Backend -ne 'bridge') {
    Note ''
    Note "The DLL talks to $Backend directly on port $port -- no bridge to keep running."
    if ($Backend -eq 'ollama') {
        Note "Make sure ollama is up and has the model:  ollama pull $Model"
    }
    Note ''
    Note 'Launch the game from Steam as usual.'
    Note 'In game: Ctrl+F4 mod version, Alt+T Thinker options, Alt+N Planetnet.'
    exit 0
}

$bridgePy  = Join-Path $Src 'bridge\chiron-bridge.py'
$bridgeCmd = Join-Path $Src 'start-bridge.cmd'
@"
@echo off
rem Start the Chiron bridge. Leave this window open while you play.
rem Generated by install.ps1 -- safe to edit or delete.
"$($python.Source)" "$bridgePy" --backend $Backend
pause
"@ | Set-Content -Path $bridgeCmd -Encoding ASCII
Note "wrote $bridgeCmd (backend: $Backend)"

if ($InstallBridgeTask) {
    $taskName = 'ChironBridge'
    $action = New-ScheduledTaskAction -Execute $python.Source `
        -Argument "`"$bridgePy`" --backend $Backend"
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName $taskName
    Note "registered scheduled task '$taskName' (starts at logon)"
} else {
    Warn 'bridge is NOT running. Start it with start-bridge.cmd before playing,'
    Warn 'or re-run with -InstallBridgeTask to start it at logon.'
}

Note ''
Note 'Launch the game from Steam as usual.'
Note 'In game: Ctrl+F4 mod version, Alt+T Thinker options, Alt+N Planetnet.'
Note ''
Note "Check the bridge is answering:  curl http://127.0.0.1:11436/health"
