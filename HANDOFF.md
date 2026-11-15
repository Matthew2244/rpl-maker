# Handoff: Magpie (working name), REAPER preset libraries from factory presets

Read this before changing anything. It says what exists, why it's shaped the way it is, and
what bit along the way. The README is for people using the app; this is for working on it.

## What it is

An app (Mac and Windows) that makes REAPER preset libraries (.RPL) from the factory presets a
person's plug-ins installed, and keeps only the presets a separate copy of REAPER loads back
exactly. It packages a workflow Matthew first ran by hand with scripts, for verified libraries
of Plugin Alliance, iZotope, XLN and UADx presets.

**The name isn't settled.** Everything people see reads `APP_NAME` in `rplmaker/__init__.py`.
The internals are deliberately neutral (the `rplmaker` package, the `RPL Maker` support
folder, the repo `rpl-maker`, bundle id `io.github.matthew2244.rplmaker`, the Windows
installer's AppId), so a rename touches the visible name only and every installed copy keeps
updating. Names offered: Magpie, Preset Hound, Squirrel, Trove, Hoardling.

## Commands

    .venv/bin/python -m rplmaker                 the window
    .venv/bin/python -m rplmaker list            what can be made (command line)
    .venv/bin/python -m rplmaker build NAME...   make and check, report at the end (--split N, --once, --min N)
    .venv/bin/python -m rplmaker access          Mac: let macOS ask about folders now
    .venv/bin/python -m rplmaker checker         remake the checking copy of REAPER
    .venv/bin/python -m rplmaker --self-test     what a build must be able to do
    ./check.sh                                   tests, compile, a help tag on every control
    .venv/bin/python tools/drive.py OUT [NAME...]   the real window, off-screen, never activated (DRIVE_STOP=s presses Stop)
    .venv/bin/python build_app.py                build for this system, ends with the built app's self-test
    .venv/bin/python tools/release_mac.py vX.Y.Z --notes NOTES.md   finish a release (below)
    .venv/bin/python tools/verify_release.py [vX.Y.Z]   the published release, checked from outside
    .venv/bin/python tools/make_icon.py          redraw assets/icon.*
    .venv/bin/python tools/make_sound_candidates.py   sound candidates and audition reels (not wired in)

## How it works

| file | does |
|---|---|
| `inventory.py` | plug-ins from REAPER's own scan cache (read, never written); walks the usual preset places; matches files to plug-ins; the scan cache |
| `formats.py` | reads .vstpreset, NKS (.nksf/.nksfx), .fxp, .aupreset, XML presets; `make_state` turns one into VST3 state |
| `states.py` | REAPER's VST3 payload layout, .RPL and presets .ini read and write, JUCE wrapping |
| `portable.py` | the checking copy of REAPER: making it, starting it hidden, handing it jobs, noticing hangs and crashes |
| `worker.lua` | runs inside the checking copy: CAPTURE, VERIFY, TOUCH, QUIT jobs, through files |
| `compare.py` | did the plug-in take the preset? decoders and the per-preset verdict |
| `pipeline.py` | the whole job per plug-in, no window; splitting; the report |
| `gui.py` | the window; `speech.py` VoiceOver and Prism; `updates.py` Sparkle and WinSparkle |
| `cli.py`, `settings.py`, `selftest.py` | command line; one JSON settings file; `--self-test` |

**Matching a file to a plug-in**, best evidence first: the VST3 class id inside the file
(.vstpreset, most NKS); else the VST2 id (NKS `VST.magic`, .fxp `fxID`, .aupreset `subtype`),
because a VST3 plug-in that grew from a VST2 one has class id `"VST" + id + name`; else a
folder on the path named like the plug-in, but only for files with no class id (a class id
that isn't installed means a different plug-in, never a folder guess). When a plug-in has
presets in several formats, the first in `formats.FORMATS` is used and the details say the
others exist. The same preset installed in two places (a library on two drives) counts once:
same name, same folder name, same bytes. A maker filing one preset under two categories
(LTL Silver Bullet: "04 Drums" and the artist's own folder) is deliberate and kept.

**Making the state.** .vstpreset and VST3 NKS are byte copies (Comp and Cont). A VST2-style
chunk (NKS, .fxp, .aupreset) goes in as it stands, or inside JUCE's VST3 wrapper (VstW +
CcnK/FBCh bank) when the plug-in's own default state is JUCE-shaped. XML goes into JUCE's
VC2! wrapper. Nothing is translated, and nothing about any one maker is hard-coded: the
checking decides what works.

**The checking copy of REAPER**, in the support folder (Mac: `~/Library/Application
Support/RPL Maker/checking-reaper`; Windows: `%APPDATA%\RPL Maker\checking-reaper`). From the
person's REAPER it only reads two files, copied: the licence (else the copy stops at the
evaluation window) and the plug-in scan cache (else it rescans everything). Remade when
REAPER changes. Its reaper.ini uses your REAPER's own plug-in folders (`vstpath64`,
`vstpath_arm64` from your reaper.ini) when you've set any, because the plug-in list names
files, not folders: a plug-in on another drive couldn't be loaded otherwise. The plug-in list
is copied again at every start, so the copy has nothing new to scan. `__startup.lua` runs `worker.lua` (copied beside the copy at each start, so
the copy never reads from inside the app), which mutes master and track before any plug-in
loads and polls `rplmaker/jobs/` on a defer loop: one job file in, `.out` written as it
goes, `.done` at the end, both deleted once read.

- **Mac:** `ditto` of REAPER.app, renamed ("REAPER for checking presets", executable
  `REAPERCheck`, bundle id `com.cockos.reaper.rplmaker-check`, `LSUIElement` so no Dock icon),
  ad-hoc signed. Started with `open -n -g -j ... --args -cfgfile <its ini> -nosplash -newinst
  -ignoreerrors -new`; found by its own executable path. The rename keeps macOS from bringing
  the person's REAPER forward instead of opening a second one, and keeps anything looking for
  a running "REAPER" by name from seeing it.
- **Windows:** REAPER runs portable when reaper.ini sits beside reaper.exe, so the copy is
  REAPER's program folder copied (found from the installer's registry entry, then the usual
  Program Files folders). Started minimised and without the focus (SW_SHOWMINNOACTIVE), its
  pid in `rplmaker/pid`, believed only if that process's image path is this copy's
  reaper.exe. **Never `os.kill(pid, 0)` on Windows**: it terminates the process.

One run at a time holds `checking.lock` (fcntl / msvcrt), so a copy found running at start is
a leftover from a run that ended badly, and is ended. Stop and Quit call `Builder.abort()`,
which closes the session for good: a job waiting on the copy ends instead of starting it
again (before that, quitting mid-run left a copy running with nothing attached).

**The verdict** (`compare.judge`), per preset: REAPER must select it by name at its own
index; then the plug-in's re-saved state must equal the file's (exact), or decode to the same
values (iZotope JSON, XLN COTT, Brainworx Pmtr, JUCE XML, JUCE ValueTree, plain XML),
comparing the keys the current plug-in still writes, at least 95% present, numbers within
1e-5, or within 0.02 for values in -1.5..1.5 (a control-step snap, counted as "rounded").
When the state is opaque, the plug-in's controls must move from their defaults ("checked by
its controls"), and two stronger rules apply: presets from different files that leave the
plug-in in exactly the same state, controls and all, are one sound (the first is kept, the
others left out naming it); and on the second check each must save back the same bytes as
the first time, unless the plug-in doesn't even do that for its own defaults. The report
says how each preset was checked.

Then each finished library is checked again (Settings, on by default) and anything failing
the second time is cut. Fewer working presets than the minimum (5 by default) and no file is
written. Each library starts "0 Default settings".

**Big sets.** Presets are checked 500 at a time (`Builder.BATCH`), so a 26,000-preset set
never sits in one preset file; indexes are rewritten across batches before judging. When a
plug-in has more presets than `split_over` (300 by default) in several folders, each folder
becomes its own library: the first level below the folder each install location's presets
share (`rel_parts` buckets by install location, so "Users" or "Volumes" never become a
folder), one level deeper when the first gives fewer than three (Addictive Drums 2: two
wrappers above 38 ADpaks). Folders under the minimum go together into "Other folders". Only
the first library carries "0 Default settings". Before a run of over 5,000 presets the window
asks first.

**The scan cache** (`scan-cache.json` in the support folder): each file's reading kept by
path, size and modification time; new files read on 8 threads, only the first 64 KB of an
NKS file. A cold scan of about 91,000 files took 7 s on an M-series Mac, a cached one 1.8 s.

## Sounds (Matthew's picks, 2026-11-14)

Picked by ear from the audition reels: **done** = synth pluck take 1, **failed** = synth pluck
take 1, **library made** = synth pluck take 2, **waiting for you** = marimba take 2. Made with
ElevenLabs sound generation on Matthew's account (his own, so fine in this public repo).
`tools/finish_sounds.py` remakes `assets/sounds/<event>.mp3` (Mac, afplay) and `.wav`
(Windows, 16-bit with dither, winsound) from the masters, in float, levelled as auditioned,
and fails if any finished file peaks over -1 dBFS (they sit at -3.2 to -3.3, no clipping;
checked identical to the candidates he heard).

When: library made (a library written), failed (a plug-in failed or wasn't made, or the run
couldn't go on), done (a run finished; nothing when stopped), waiting (checking is waiting on
macOS's folder question, once a run). **Sounds and speech take turns** (`MainFrame.cue`): a
queue where each item plays its sound, says its sentence when the sound has ended, then
waits about 0.28 s a word before the next sound, so a sound never lands on speech or speech
on a sound (checked off-screen with sounds recorded, never played). `sounds.play` also never
overlaps two sounds and plays library made at most every 2 s. Settings, Play sounds turns
them off; then sentences come at once. Stop clears what's still queued.

## Updates

Sparkle 2.10.0 on the Mac (in Contents/Frameworks, without its XPC services, signed inside
out), WinSparkle 0.9.4 on Windows (only in an installed copy: it updates by running the new
installer). Both are driven with ctypes from `updates.py`, checksums pinned in
`build_app_support.py`. **Updates are heard, never popped up**: neither updater checks by
itself; the app reads the update list 15 seconds after opening and every 4 hours, and says
"Magpie X is out. Help, Check for Updates shows what's new and installs it." once per
version, politely, only with its window in front. Help, Check for Updates (Command-U,
Control-U) opens the updater's window; without one (from source) it opens the releases page.

The update lists are release assets, `releases/latest/download/appcast.xml` and
`appcast-windows.xml`. **Every release must carry both.**

**The signing key** is this app's own EdDSA key, separate from any other app's, in the
Studio's login Keychain: "Private key for signing Sparkle updates", service
`https://sparkle-project.org`, account `rpl-maker`, made 2026-11-14. Public half:
`jTFOt+znz5fHM/9/JsRJfm5aaz7S3XDQ+st0AMWacYk=` (in `build_app_support.py` and
`updates.py`). **Lose the private key and no installed copy will accept another update.**
`tools/appcast.py` has Sparkle's `generate_keys` export it into a private temporary folder
for `sign_update`, then overwrites and removes it. **Backed up** (2026-11-14) in Matthew's
1Password as the secure note "Magpie (rpl-maker) Sparkle signing key (EdDSA)", checked to
match exactly. To export it again, never into the repo:

    "$(.venv/bin/python -c 'import build_app_support as b; print(b.sparkle_bin())')/generate_keys" --account rpl-maker -x KEYFILE

Restore on another Mac: `generate_keys --account rpl-maker -f KEYFILE`.

## Building and releasing

**Mac releases are built with `.venv-release`**: python-build-standalone 3.13 (checksum
checked, in `~/Library/Caches/rpl-maker-build/`), wxPython 4.3.1, PyInstaller. Homebrew's
Python is built for the macOS it's on (26), and every library it brings needed macOS 26;
with the standalone build the newest any library needs is macOS 12 (wxWidgets). Apple
silicon only for now (the standalone build is arm64).

A release: bump `VERSION`, push, `gh release create vX.Y.Z --notes-file NOTES.md` (CI builds
the Windows installer from the tag, installs it quietly, runs the installed self-test,
uninstalls, and attaches `Magpie-Setup.exe`), then on the Studio
`.venv/bin/python tools/release_mac.py vX.Y.Z --notes release-notes/X.Y.Z.md`: Developer ID
with the hardened runtime, notarize, staple, Gatekeeper, the signed app's self-test, the Mac
zip and appcast.xml uploaded, then appcast-windows.xml if CI has attached the installer. If it
hadn't yet: `tools/release_mac.py vX.Y.Z --windows-only --notes ...` once it has (no rebuild).
Last, it runs `tools/verify_release.py`: both `latest/download` update lists name this
version and this tag's files, each download matches its length and EdDSA signature against
the app's public key (openssl), and the downloaded Mac app passes codesign and Gatekeeper as
Notarized Developer ID.
It waits up to 3 minutes for `latest/download` to show the new version: right after an
upload GitHub served 0.1.2's list for a while, and the 0.1.3 check failed on that alone.

**Never check a release by hand in a temporary folder and leave it.** The 0.1.0 check did
(`$TMPDIR/tmp_se0gq4i/Magpie.app`), and on 2026-11-15 macOS showed "Magpie.app is damaged":
macOS registers any app it sees, then clears old temporary files a piece at a time. The
script downloads into one folder, unregisters the unzipped app (`lsregister -u`), never runs
it, and always removes the folder. Cleaned up then: that copy unregistered and removed.

**Released:** v0.1.0 and v0.1.1 (sounds) 2026-11-14; v0.1.2 2026-11-15 (Windows report fix,
your REAPER's plug-in folders, Windows-safe file names; `release-notes/0.1.2.md`); v0.1.3
2026-11-15 (the first-run folder access question; Windows Documents from the system, since
OneDrive often moves it; `release-notes/0.1.3.md`). v0.1.4 2026-11-15 (Windows parity: Check Folder
Access, check states, names and help tags through MSAA, the copy hidden; `release-notes/0.1.4.md`).

Windows has no code signing certificate, so SmartScreen may warn; the README says what to do.
Updates are still protected: WinSparkle checks the EdDSA signature first.

## House rules (from Wavelength)

**Mac and Windows get the same things (Matthew, 2026-11-15: "you gotta make sure everyone has
the same stuff").** Anything a Mac user gets, a Windows user gets the equivalent of, in the same
release. When the Mac feature can't exist on Windows, build what does the same job there
(folder access below is the model), and record here anything that can't be made equal and why.

How Windows matches (0.1.4, checked on CI by `tools/win_acc_check.py`, which reads the window
through MSAA the way NVDA and JAWS do, and by unit tests on windows-latest):

| Mac | Windows |
|---|---|
| `speech.label` sets the VoiceOver name | `wx.Accessible` answers MSAA with the same name (`speech._windows_accessible`) |
| VoiceOver reads help tags | each help tag is the control's MSAA description (`speech.windows_help_tags`), read after the name |
| check list rows read once, as checkboxes (`mac_check_list_reads_once`) | rows answer as checkboxes with their checked state (wx's owner-drawn CheckListBox gave none), and a state change is announced (`speech.row_changed`) |
| Allow Folder Access, and the first-run question | Check Folder Access (`access.py`), the same question |
| Escape on "Not Now" given by hand (`escape_presses`) | Windows gives Escape to the Cancel button whatever its label |
| the copy is `LSUIElement`: no Dock icon, no Command-Tab | the copy's windows are hidden at start (`portable._win_hide`): no taskbar, no Alt-Tab |
| VoiceOver priority 50/90 | Prism `interrupt` False/True |
| Sparkle, heard not popped up | WinSparkle, the same |
| sounds .mp3 through afplay | the same sounds as .wav through winsound |

**Can't be made equal, and why:**
- The copy's name. On the Mac it's renamed "REAPER for checking presets"; on Windows it's still
  reaper.exe (Task Manager shows REAPER), because renaming the program hasn't been tried with a
  real Windows REAPER and portable mode or plug-ins might depend on it. Hidden windows make it
  much less likely anyone meets it.
- Choosing a quiet audio device for the copy (`quiet_device`) is Mac-only: REAPER on Windows
  isn't known to ask on first run, and its audio settings there haven't been tried. The worker
  mutes master and track on both systems, so nothing is heard either way.
- Menu placement: Settings, About and Quit live in the Mac's app menu (macOS puts them there);
  on Windows they're in File and Help. Same names, same shortcuts.
- Nothing Windows-side has been heard with a real screen reader yet; MSAA reads on CI are the
  nearest check.

Native controls; every control has a spoken name and a help tag (`check.sh` counts them);
controls are made label first, because VoiceOver reads a Mac window in creation order; rows
say their status first; nothing talks on a timer; finishes and failures are spoken, politely
unless someone is waiting on them; the end of a run always; every shortcut means one thing;
everything works from the keyboard. Wording is plain: one sentence per reason, never the
same words read out sixty times (`pipeline.reason_lines` groups left-out presets by reason).

## Tested

On an Apple silicon Mac with REAPER 7.85, every preset loaded and judged, checked twice:

| plug-in | source | result | how |
|---|---|---|---|
| Ozone 12 Equalizer, Vintage EQ, Vintage Limiter, Dynamic EQ, Exciter | NKS, VST3 state | all | byte-identical |
| bx_glue, bx_rooMS | .vstpreset | 88/88, 200/200 | every value (Pmtr) |
| LTL SILVER BULLET mk2 | XML in JUCE's VC2! wrapper | 267/267; split by folder, 15 libraries | every value |
| Unfiltered Audio Zip | NKS, VST2 JUCE chunk, wrapped | 109/115 | the 6 left out use modulators |
| Pianoteq 9 | NKS, VST2 chunk | 799/800 | controls only: its state names a factory preset |
| Massive X | NKS | 0/64, not made | correctly refused: its NKS data isn't its VST3 state |

0.1.2 checked on the Mac with the real window off-screen (`tools/drive.py`, bx_glue 88/88 with
the copy using the Studio's own plug-in folders) and 28 unit tests, which CI also runs on
Windows; the report's date is one of them, since `%-d` stopped the report there.

Also: Stop part-way through a plug-in (finished libraries kept, the rest reported), quitting
mid-run (the copy ends and isn't restarted), batches across the 500 boundary (Pianoteq: same
799), the notarized app's own binary making a library, 22 unit tests.

**Not tested on a real Windows PC.** CI builds the installer, installs it, runs the installed
app's self-test (window code, WinSparkle, Prism load) and uninstalls. Nobody has yet run the
window with NVDA, JAWS or Narrator, made a library with a Windows REAPER, or updated through
WinSparkle. Things that might need work there: whether the portable copy of REAPER asks
anything on its first run (on the Mac it asked which audio device to use, until reaper.ini
named one), whether starting it minimised really keeps it out of the way, the preset folders
searched (`inventory.SEARCH_ROOTS`), and how NVDA reads the check list. Before 0.1.2 a Windows
run could never finish (the report's `%-d` raised in the run's thread and the window stayed
busy); nobody on Windows had got that far, which says how untested it is.

## Things that bite

1. **macOS asks before a new app opens Documents, Desktop or another drive, and the plug-in
   stops there until someone answers.** Some plug-ins scan their own preset folders as they
   load (Native Instruments effects, Surge XT) and hang inside `TrackFX_AddByName` on an
   `open()` that never returns, with no window in REAPER. A copy of REAPER doesn't share
   REAPER's own permissions, even an untouched Cockos-signed copy. So capture waits up to 4
   minutes, says once after 8 s that macOS may be asking and to choose Allow; File, Allow
   Folder Access opens each place from the copy so the questions come together. The copy is
   ad-hoc signed, so remaking it after a REAPER update probably means answering again.
   **The person decides (Matthew, 2026-11-15: "the user should decide on that").** Since
   0.1.3, the first Make Libraries on a Mac asks once (`MainFrame.ask_about_access`, setting
   `access_asked`): Allow Folder Access Now runs the access pass and then the run, Not Now
   just runs. Never asked again; also never asked once the menu item has been used. macOS
   gives Escape only to a button titled "Cancel", so `gui.escape_presses` gives it to
   "Not Now" from a wx timer inside the alert's modal loop (wx timers run in the common run
   loop modes); checked on an unshown NSAlert, not yet by ear. `tools/drive.py` sets
   `access_asked` so a test never puts that alert on the screen.
   **Windows, since 0.1.4 (parity):** the same one-time question, "Check Folder Access?"
   (Check Folder Access Now / Not Now; Windows gives Escape to the Cancel button whatever its
   label), and File, Check Folder Access. Windows asks nothing ahead of time, so "check"
   means `access.check`: list every folder presets were found in, the usual places and the
   person's extra folders (those must exist), save and remove a test file in the libraries
   folder, and read Controlled Folder Access ("ransomware protection") from the registry
   (policy key first; 1 or 3 on, 2 or 4 audit; unreadable is None, never an error; not
   Get-MpPreference, which is a slow PowerShell start). Problems go in a message window that
   reads line by line: each folder by name, and the Windows Security steps to allow Magpie
   when a save fails with protection on. The run starts after it only if libraries can be
   saved. The libraries folder and the VST3 Presets search use the real Documents
   (SHGetKnownFolderPath; OneDrive moves it). A failed save at the start of a run also gives
   those steps when protection is on. `rplmaker access` does the same from the command line.
   **Never tested with someone answering Allow.** Don't use those plug-ins in automated tests:
   the questions appear on the screen of whoever is at the Mac.
2. **REAPER's first-run audio question stops the copy before any script runs**, unless
   reaper.ini names input and output devices that exist. `portable.quiet_device()` names an
   output-only device that isn't the main one, so no microphone is opened (another macOS
   question) and nothing could reach the speakers in use; the worker mutes master and track
   anyway. Rewritten at every start, since devices come and go.
3. **REAPER caches folder listings for `EnumerateFiles`.** The worker calls
   `EnumerateFiles(dir, -1)` first, and skips a job it reads as empty instead of deleting it.
4. **The preset list is read fresh** each time a plug-in is added, so capture and checks run
   in one session.
5. **Variant names.** "Blue Cat's Gain 3 (Dual) (Blue Cat Audio)": only channel counts and
   architectures are dropped from the end, then the maker; "(Dual)" stays, or the Dual, Mono
   and Stereo libraries would share a file name. A run also never writes two libraries to one
   path.
6. **A windowed Windows build may start with no stdout**: `app.py` reopens it, or the
   self-test prints nowhere.
7. **Never `ditto` over an existing app bundle**: it merges, leaving the old build's files
   inside. Move the old copy to the Trash first.

   **On the Studio, a never-run copy at exactly /Applications/Magpie.app hangs on its first
   run** (2026-11-14, investigated, not an app bug). The process sits at `_dyld_start`:
   only the program file and dyld mapped, 32 KB, no Python, no settings or lock file open,
   so none of the app's code has run (moving checking.lock away changed nothing). Tested:
   the same never-run copy runs from dist, the scratchpad, or /Applications under any
   other name; a copy that has run once anywhere runs fine when moved to that path; a
   never-run copy written there or moved there hangs, with or without unregistering the
   path from LaunchServices (its provenance tag can't be removed). Gatekeeper accepts it
   as notarized; no prompt on screen, nothing in the log, no third-party security software.
   So it's macOS state for that one path on that Mac, most likely from the earlier copy at
   that path, never seen elsewhere. **Installing there: run the copy's self-test somewhere
   else first, then move it in** (that's how 0.1.0 is installed, and its self-test passes
   from /Applications). Watch the first Sparkle update on the Studio: Sparkle moves a
   never-run copy into place, which is the case that hangs. A restart may clear it;
   untested.
8. **Sound candidates** (`tools/make_sound_candidates.py`): level by loudness
   and cap the peak before MP3, then check the encoded file. Levelled to a -1.5 dBFS peak,
   the bright ones came out at 0.0 after encoding.

## Not done

- The name; an Intel Mac build; Windows code signing. The sounds haven't been heard on Windows.
- Testing on Windows with a screen reader and a real REAPER (see Tested).
- Allow Folder Access with someone answering, and the first-run question heard with VoiceOver.
- The packaged Mac app's own scan reads Documents and other drives, so macOS will ask about
  Magpie too when it's opened from the Finder (Info.plist says why).
- Omnisphere-sized sets: its two install locations are laid out differently, so folders
  split unevenly; a full run takes hours.
- An independent check for opaque states using REAPER's own loading of a maker's .vstpreset.
- AU plug-ins; the iZotope `.preset` JSON (deliberately not: it stores enums as words and the
  mapping lives inside each plug-in).
