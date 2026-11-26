# Magpie

Magpie makes REAPER preset libraries (.RPL files) from the factory presets your plug-ins
already installed, and keeps only the presets REAPER really loads. It runs on Mac and
Windows.

Magpie is a working name. It may change.

Magpie isn't made by or affiliated with Cockos, the makers of REAPER, or with any plug-in
maker. You need your own copy of REAPER, and the plug-ins you make libraries for.

## Who it's for

REAPER users who'd like their plug-ins' factory presets in REAPER's own preset menu, where
they can be picked by name from the keyboard. It was made with screen readers in mind first,
and it works the same way if you don't use one.

## What it does

1. It reads REAPER's own list of your VST3 plug-ins, then looks for the preset files their
   makers installed: VST3 presets, Native Instruments NKS presets, VST2 preset files, Audio
   Unit presets and XML presets.
2. You check the plug-ins you want and choose Make Libraries.
3. Every preset is loaded by name in a separate, hidden copy of REAPER, and the plug-in's own
   saved settings are compared with the preset file. A preset that doesn't come back the same
   is left out. Each finished library is checked a second time.
4. You get a folder of .RPL files, one per plug-in (or one per folder or category for big
   sets), and a report saying what was made, what was left out and why. Preset names start
   with their maker's category, so they stay grouped in REAPER's list.

Your own REAPER, its settings and its presets are never changed. The separate copy reads
from your REAPER its licence, its list of plug-ins, and two things from its settings file:
the folders it looks for plug-ins in, and its note that you accepted REAPER's licence
agreement. Magpie also reads your REAPER's presets folder, to notice plug-ins already done.
The copy uses no sound device on Windows (REAPER's Dummy Audio), and on a Mac an output-only
one that isn't your main one when there is one, so it never stops to ask which to use. It
mutes itself before loading any plug-in either way.

Libraries are saved in a folder called REAPER Preset Libraries in your Documents folder,
with a folder for each maker and one for each plug-in inside it. You can choose another
folder in Preferences.

## What you need

### On a Mac

- A Mac with Apple silicon (M1 or later). There's no Intel build yet.
- macOS 12 or later.
- REAPER 7.

### On Windows

- 64-bit Windows.
- REAPER 7.

The Windows version hasn't yet been tried by a person with a screen reader, or with a real
copy of REAPER on Windows. Each release is installed and tested on Windows by GitHub's build
machines, and they read the window the way NVDA and JAWS do. If you try it on Windows, please
tell me how it goes.

## Download

Get the latest release from the
[releases page](https://github.com/Matthew2244/rpl-maker/releases/latest). It has two
downloads:

- [Magpie-mac.zip](https://github.com/Matthew2244/rpl-maker/releases/latest/download/Magpie-mac.zip) for the Mac.
- [Magpie-Setup.exe](https://github.com/Matthew2244/rpl-maker/releases/latest/download/Magpie-Setup.exe) for Windows.

## Installing

### On a Mac

1. Open Magpie-mac.zip. It unzips to Magpie.
2. Move Magpie to your Applications folder.
3. Open it from Applications.

It's signed and notarized, so macOS opens it without a warning about who made it.

### On Windows

1. Run Magpie-Setup.exe.
2. Windows SmartScreen may say it protected your PC, because the installer isn't code signed
   yet. Choose More info, then Run anyway.
3. Follow the installer. It installs for you only, so it doesn't ask for an administrator
   password. It can also put Magpie on your desktop if you want.

Magpie is then in the Start menu. To uninstall it, use Settings, Apps. Uninstalling leaves
your settings and libraries alone.

## The first time you make libraries

Magpie asks one question about folder access, once, the first time you choose Make
Libraries. Escape is Not Now. Either way it isn't asked again, and the same thing is in the
File menu any time.

### On a Mac

Some plug-ins look through your Documents folder or other drives as they load. The first
time the checking copy of REAPER does that, macOS asks whether "REAPER for checking presets"
may open files there, and checking waits until someone answers.

Magpie asks whether to Allow Folder Access Now. That opens each of those places once, so
macOS asks its questions together while you're there. Choose Allow for each. Then your
libraries are made. Not Now starts making them straight away. File, Allow Folder Access does
the same thing whenever you like.

macOS may also ask about Magpie itself the first time it looks for presets in Documents or
on another drive.

### On Windows

Windows doesn't ask about folders the way a Mac does. A preset folder can still be out of
reach, though, and Windows Security's ransomware protection (Controlled Folder Access) can
stop new apps saving in Documents.

Magpie asks whether to Check Folder Access Now. That reads every preset folder and saves a
test file where libraries go. It names any folder it can't read. If ransomware protection
stops the save, it says so and gives the steps in Windows Security to allow Magpie, or you
can choose another folder in Preferences. Then your libraries are made. Not Now starts making
them straight away. File, Check Folder Access does the same thing whenever you like.

## Plug-ins already in REAPER

If you've already put a plug-in's presets into REAPER yourself, by hand or by importing a
library, Magpie notices. That plug-in's row starts "Already in REAPER", it's left unchecked,
and Check All Shown skips it. You can still check it with Space and make it anyway. The
details say what was found.

How it tells: REAPER keeps each plug-in's own presets in a file in its presets folder. Almost
every plug-in gets one of those as soon as it's used, often holding only a default entry, so a
file being there means nothing. A plug-in counts as already in REAPER only when that file holds,
by name, at least half of the preset names Magpie found for it, and at least 3 of them. Entries
called Default, Init, Untitled or Program 1, and ones with no name, never count. Names are
compared ignoring capitals, spaces and punctuation. Magpie looks at the plug-in's VST3, VST2,
AU and CLAP versions; when only another version has them, the row says which, because those
presets don't load in the VST3 version. It reads the presets folder in REAPER's usual place
(Mac: Library, Application Support, REAPER; Windows: AppData, Roaming, REAPER), the same place
it reads REAPER's plug-in list from; a portable REAPER isn't looked at. REAPER's files are only
read, never changed.

## Plug-ins REAPER hasn't scanned yet

Magpie learns which plug-ins you have from REAPER's own list, and REAPER only adds a plug-in to
that list when it starts and scans it. So a plug-in installed since REAPER last started isn't
there yet. When Magpie finds plug-ins like that in your plug-in folders, it says how many after
Look for Presets Again, and names them.

File, Scan New Plug-ins has the checking copy of REAPER scan them. Your REAPER and its list
aren't changed; the copy keeps what it found in its own list. Then they show up like any other
plug-in. A big instrument can take a minute or more to scan, and on a Mac a plug-in may make
macOS ask whether REAPER for checking presets can open a folder: choose Allow. From the command
line it's `rplmaker scan-new`. Libraries made for these plug-ins work in your REAPER once it has
scanned them too, which it does the next time it starts.

## Keeping presets organized

REAPER shows a plug-in's presets as one list, sorted by name. It has no folders or submenus
for presets, and every library you import for a plug-in goes into that same list. So Magpie
keeps each category together by its name.

### Categories in preset names

Preferences, Start preset names with their category, is on at first. A preset in the maker's
Bass category is then called "Bass - Deep Sub", and all the Bass presets sit together in
REAPER's list, away from "Lead - Saw".

- Categories come only from the plug-in's maker: the folders its presets were installed in,
  or the category written inside the preset file (Native Instruments NKS presets carry one,
  and some VST3 presets do). Magpie never guesses a category from the words in a name, so a
  preset is never put in a category its maker didn't give it.
- A category the maker put on every preset (all of a plug-in's presets called EQ, say) isn't
  added, because it wouldn't group anything.
- A preset without a category keeps its name as it is.
- A name that already starts with its category, such as "Bass - Round" or "Bass_Round", isn't
  given it twice.
- Two presets that would end up with the same name get (2) after the second.

Plenty of plug-ins don't come with categories. Most Plugin Alliance effects, for example, put
every preset in one folder, so their names stay as they are.

### Folders

Libraries are saved in a folder for each maker, then a folder for each plug-in, such as
Plugin Alliance, then bx_glue. That makes one plug-in's libraries easy to find, and easy to
share. Preferences, Folders for libraries, can put them all in the maker's folder instead, the
way Magpie did before version 0.2.0.

Preferences, One library per category, is off at first. Turned on, each category gets its own
file, such as "Knif Audio Knifonium - Bass VST3i.RPL", so you can import only the ones you
want. Names still start with their category, because REAPER puts every library you import for
a plug-in into one list. Only the first file has "0 Default settings". Categories with fewer
presets than the smallest library worth keeping go together in a file called Other. With it
off, a plug-in gets one file, except big sets: more than 300 presets in several folders or
categories are split anyway, which Preferences can also change.

File and folder names avoid everything Windows can't save: the characters it refuses, names
like CON and NUL, and names so long that a copy in someone's Downloads folder would pass
Windows' path limit. So a library made on a Mac can be copied to a PC as it is.

### Organizing libraries you already have

File, Organize Existing Libraries, does the same for libraries you already have, your own or
ones you downloaded from the Hoard. Choose a folder of .RPL files. Magpie makes an organized
copy beside it, with the same name and (organized) at the end. The folder you chose isn't
changed.

- Folders the libraries are already in are kept, with a folder for each plug-in added inside.
  A library that isn't in any folder goes in a folder for its maker.
- Preset names get their categories when the plug-in and its preset files are on this
  computer, so Magpie can see which category each preset came from. Otherwise names stay as
  they are, and only the folders change.
- Other files in the folder, such as a read-me, are copied as they are.
- Renaming a preset only changes its name. The settings it holds are copied byte for byte.
- The report, in Open Report, lists every file and says how many names changed. It's saved
  in Magpie's own folder, not among the libraries, so a folder you're sharing holds only the
  libraries.

## Using a library in REAPER

1. Put the plug-in on a track, so its FX window is open.
2. Open the FX window's preset menu: the button named Presets and Performance Management.
   With OSARA, Tab to it, then press Shift+Space.
3. Choose Import preset library, and pick the .RPL file.

The presets are now in the plug-in's preset list on every track. Each library starts with
"0 Default settings", the plug-in as it loads fresh. Help, How to Import a Library in Magpie
says the same.

## Keyboard shortcuts

Everything works from the keyboard. The shortcuts are the same on both systems, with
Command on a Mac and Control on Windows. Two match what REAPER users already know:
Preferences is REAPER's own Preferences key, and Say Progress is OSARA's Report selection key.

### On a Mac

- Command-B: Make Libraries
- Command-Period: Stop
- Command-R: Look for Presets Again
- Command-F: go to Find
- Command-L: go to the plug-in list
- Command-Shift-Space: say what's happening now (OSARA's Report selection key)
- Command-Shift-A: Check All Shown
- Command-Shift-U: Uncheck All
- Command-Shift-F: Show Libraries in Finder
- Command-Shift-R: Open Report
- Command-Shift-O: Organize Existing Libraries
- Command-U: Check for Updates
- Command-P: Preferences (in the Magpie menu), as in REAPER. Command-Comma opens them too.
- Command-Q: Quit (in the Magpie menu)
- Space, in the plug-in list: check or uncheck the selected plug-in

### On Windows

- Control+B: Make Libraries
- Control+Period: Stop
- Control+R: Look for Presets Again
- Control+F: go to Find
- Control+L: go to the plug-in list
- Control+Shift+Space: say what's happening now (OSARA's Report selection key)
- Control+Shift+A: Check All Shown
- Control+Shift+U: Uncheck All
- Control+Shift+F: Show Libraries in File Explorer
- Control+Shift+R: Open Report
- Control+Shift+O: Organize Existing Libraries
- Control+U: Check for Updates
- Control+P: Preferences (in the File menu), as in REAPER. Control+Comma opens them too.
- Control+Q: Quit (in the File menu)
- Space, in the plug-in list: check or uncheck the selected plug-in

About Magpie is in the Magpie menu on a Mac and the Help menu on Windows.

## Screen readers

Every control has a spoken name and a help tag. The window reads top to bottom: Find, Show,
the plug-in list, the details for the selected plug-in, the buttons, then progress. Each row
in the list says its status first. Select a plug-in, then Tab to Details to read what was
found for it.

Results are spoken as each plug-in finishes, without moving you. The end of a run is always
spoken, and so is the end of organizing: how many libraries, how many had categories, and how
many names changed. A short sound plays when a library is made, when one can't be made, when a run is
done, and when checking is waiting on you. What's said comes after the sound, never on top of
it. Preferences has switches for the sounds and for the spoken results.

### VoiceOver on a Mac

Magpie talks through VoiceOver. Help tags are read the usual way, after a pause or with
VoiceOver-Shift-H. Plug-ins in the list read as checkboxes, checked or not.

### NVDA, JAWS and Narrator on Windows

Magpie talks through the screen reader you're running, including NVDA and JAWS. With
Narrator, it uses Windows' own notifications, which Narrator reads. It never falls back to a
separate voice, so if no screen reader is running, nothing talks over you.

Plug-ins in the list read as checkboxes with their checked state, and checking one says so.
Each control's help tag is read after its name, as its description.

## Good to know

- A plug-in that needs activating, or shows a window as it loads, can't be checked. It's
  reported, and the run carries on with the next one.
- Some presets can't be made into REAPER presets, because the plug-in keeps them in a form
  only it reads. Those are counted in the report as files that couldn't be read.
- Libraries with fewer than 5 working presets aren't saved. You can change that in Preferences.
- When a plug-in has more than 300 presets in several folders or categories, each becomes
  its own library. You can turn that off or change the number in Preferences.
- If your presets are somewhere unusual, such as a Native Instruments User Content folder on
  another drive, add that folder in Preferences, under Also look for presets in.
- The report opens in TextEdit on a Mac and Notepad on Windows.

## Updates

Magpie looks for a new version 15 seconds after it opens, then every 4 hours while it's
open. When there is one, it says so once, without a window popping up, and only when
Magpie's window is in front. Help, Check for Updates shows what's new and installs it.

On a Mac, updates come through Sparkle. On Windows, they come through WinSparkle, which runs
the new installer for you. Both check each update's signature before installing it.

What changed in each version is on the
[releases page](https://github.com/Matthew2244/rpl-maker/releases), and in the
release-notes folder of this repository.

## Reporting a problem or asking for something

Please [open an issue](https://github.com/Matthew2244/rpl-maker/issues/new/choose). There's
a form for problems and one for ideas. It helps to say:

- Which version of Magpie you have. Help, About Magpie on Windows, or Magpie, About Magpie on
  a Mac.
- Your system and its version, such as macOS 15 or Windows 11.
- Your screen reader and its version, if you use one.
- Your version of REAPER.
- What you did, what happened, and what you expected.

If a run went wrong, the report from Open Report is useful too. You can paste it in.

## Running from source

    python3 -m venv .venv
    .venv/bin/pip install wxPython
    .venv/bin/python -m rplmaker            # the window
    .venv/bin/python -m rplmaker list       # what can be made, from the command line
    .venv/bin/python -m rplmaker build NAME
    .venv/bin/python -m rplmaker access     # Allow or Check Folder Access, from the command line
    .venv/bin/python -m rplmaker organize FOLDER [--per-category] [--no-prefix] [--layout maker]

On Windows, use `.venv\Scripts\python` in place of `.venv/bin/python`. Spoken results on
Windows also need Prism (`pip install prismatoid`); without it, the window still works and the status line
shows what's happening.

`HANDOFF.md` explains how it works inside.

## License

MIT. See `LICENSE`.
