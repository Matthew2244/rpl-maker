# Magpie

Magpie makes REAPER preset libraries (.RPL files) from the factory presets your plug-ins
already installed, and keeps only the presets REAPER really loads.

Magpie is a working name. It may change.

Magpie isn't made by or affiliated with Cockos, the makers of REAPER, or with any plug-in
maker. You need your own copy of REAPER, and the plug-ins you make libraries for.

## What it does

1. It reads REAPER's own list of your VST3 plug-ins, then looks for the preset files their
   makers installed: VST3 presets, Native Instruments NKS presets, VST2 preset files, Audio
   Unit presets and XML presets.
2. You check the plug-ins you want and choose Make Libraries.
3. Every preset is loaded by name in a separate, hidden copy of REAPER, and the plug-in's own
   saved settings are compared with the preset file. A preset that doesn't come back the same
   is left out. Each finished library is checked a second time.
4. You get a folder of .RPL files, one per plug-in (or one per folder for big sets), and a
   report saying what was made, what was left out and why.

Your own REAPER, its settings and its presets are never changed. The separate copy reads
two files from your REAPER: its licence and its list of plug-ins.

It was made with screen readers in mind first. Every control has a name and a help tag,
results are spoken as they finish, and everything works from the keyboard. It works with
VoiceOver on the Mac, and with NVDA, JAWS and Narrator on Windows.

## Getting it

Download the latest release from the
[releases page](https://github.com/Matthew2244/rpl-maker/releases/latest).

- **Mac:** `Magpie-mac.zip`. Unzip it and move Magpie to Applications. It's signed and
  notarized. It needs a Mac with Apple silicon (M1 or later), macOS 12 or later, and REAPER 7.
- **Windows:** `Magpie-Setup.exe`. It installs for you only and doesn't ask for an
  administrator password. The installer isn't code signed, so Windows SmartScreen may say it
  protected your PC. Choose More info, then Run anyway.

Magpie tells you when there's a new version, once, without a window popping up. Help, Check
for Updates installs it.

## Using a library in REAPER

1. Put the plug-in on a track, so its FX window is open.
2. Open the FX window's preset menu: the button named Presets and Performance Management.
   With OSARA, Tab to it, then press Shift+Space.
3. Choose Import preset library, and pick the .RPL file.

The presets are now in the plug-in's preset list on every track. Each library starts with
"0 Default settings", the plug-in as it loads fresh.

## Good to know

- **Mac:** some plug-ins look through your Documents folder or other drives as they load.
  The first time the checking copy of REAPER does that, macOS asks whether "REAPER for
  checking presets" may open files there, and checking waits until you answer. File, Allow
  Folder Access asks about all of those places at once, before you start.
- A plug-in that needs activating, or shows a window as it loads, can't be checked. It's
  reported, and the run carries on with the next one.
- Some presets can't be made into REAPER presets, because the plug-in keeps them in a form
  only it reads. Those are counted in the report as files that couldn't be read.
- Libraries with fewer than 5 working presets aren't saved. You can change that in Settings.

## Running from source

    python3 -m venv .venv
    .venv/bin/pip install wxPython
    .venv/bin/python -m rplmaker            # the window
    .venv/bin/python -m rplmaker list       # what can be made, from the command line
    .venv/bin/python -m rplmaker build NAME

`HANDOFF.md` explains how it works inside.

## License

MIT. See `LICENSE`.
