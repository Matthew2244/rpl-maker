"""Build and check libraries: the whole job for a list of plug-ins, with no window attached.

For each plug-in:
  1. The checking copy of REAPER loads it fresh and hands over its default state, which
     becomes "0 Default settings" and the template every preset is fitted into.
  2. Every preset file is turned into a REAPER preset (a byte copy of the plug-in's own
     state; some formats need the plug-in's own wrapper around them).
  3. The checking copy loads each one by name and the plug-in saves its settings back;
     `compare.judge` decides whether they match what the file holds.
  4. What passed is written as a library and checked a second time, as the finished file.
     Anything that fails then is cut too: a preset that only works sometimes isn't kept.
  5. A library with fewer working presets than the smallest worth keeping isn't written.

A plug-in that takes REAPER down or stops it responding costs that one preset (or that
plug-in), never the run: the copy is restarted and the next one carries on.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import time
from dataclasses import dataclass, field

from . import compare, formats, inventory, organize, portable, states
from .inventory import Plugin

DEFAULT_NAME = "0 Default settings"
STUCK_WORDS = ("The plug-in stopped REAPER responding as it loaded, for 4 minutes. It may have been waiting "
               "for an activation" + (", or for a window of its own to be closed." if portable.WIN else
                                      ", or for macOS to allow it into a folder (File, Allow Folder Access asks "
                                      "for that ahead of time)."))


@dataclass
class Result:
    plugin: Plugin
    fmt: str | None = None
    status: str = "waiting"          # made, dropped, failed, stopped
    file: str | None = None
    kept: list = field(default_factory=list)       # (name, how)
    cut: list = field(default_factory=list)        # (name, why)
    unreadable: list = field(default_factory=list)  # (file, why)
    files: list = field(default_factory=list)       # (path, presets in it)
    small: list = field(default_factory=list)       # (folder, working presets) too few to keep
    split: bool = False
    note: str = ""
    seconds: float = 0.0

    @property
    def tried(self) -> int:
        return len(self.kept) + len(self.cut) + sum(n for _l, n in self.small)

    def sentence(self) -> str:
        """One plain sentence, status first, for the list and for speech."""
        p = self.plugin
        n_kept = len(self.kept)
        if self.status == "made":
            s = f"Made: {p.name}, {n_kept} of {self.tried} presets work"
            if len(self.files) > 1:
                s += f", in {len(self.files)} libraries"
            if self.unreadable:
                s += f", {len(self.unreadable)} files couldn't be read"
            return s + "."
        if self.status == "dropped":
            return f"Not made: {p.name}. {self.note}"
        if self.status == "failed":
            return f"Failed: {p.name}. {self.note}"
        if self.status == "stopped":
            return f"Stopped: {p.name}, part way through checking. Nothing was saved for it."
        if self.status == "skipped":
            return f"Not started: {p.name}. The run was stopped first."
        return f"Waiting: {p.name}."


def grouped(cut: list) -> list[tuple[str, list[str]]]:
    """Left-out presets grouped by reason, biggest group first: one sentence per reason
    instead of the same words read out sixty times."""
    groups: dict[str, list[str]] = {}
    for name, why in cut:
        groups.setdefault(why, []).append(name)
    return sorted(groups.items(), key=lambda g: -len(g[1]))


def reason_lines(cut: list, limit_names: int = 12) -> list[str]:
    out = []
    for why, names in grouped(cut):
        if len(names) == 1:
            out.append(f"Left out: {names[0]}: {why}.")
        else:
            shown = ", ".join(names[:limit_names]) + (f", and {len(names) - limit_names} more" if len(names) > limit_names else "")
            out.append(f"{len(names)} left out because {why}: {shown}.")
    return out


def safe_file_name(s: str) -> str:
    """A name every system can save (organize.safe_name): a library made on a Mac may be
    copied to a PC."""
    return organize.safe_name(s)


def rel_parts(found: list) -> list[list[str]]:
    return organize.rel_parts([f.path for f in found])


def preset_names(found: list, prefix: bool = True) -> list[str]:
    """'Category - Name', the category from the maker's folders or files (organize.py)."""
    return organize.preset_names(found, prefix)


def preset_groups(found: list) -> list[str]:
    """The category each preset's library is split by, '' for none (organize.py)."""
    return organize.preset_groups(found)


def got_comp(line):
    """The component state the plug-in saved back, from a worker P line (None if none)."""
    if not line or not line.startswith("P\t"):
        return None
    try:
        return states.parse_state(states.chunk_state(line.split("\t", 6)[6].split("|")))["comp"]
    except Exception:  # noqa: BLE001
        return None


def file_name(p: Plugin, author: str, part: str | None = None, n: int = 0) -> str:
    by = f" by {author.strip()}" if author.strip() else ""
    if part and part.lower().startswith(p.name.lower() + " - "):
        part = part[len(p.name) + 3:]      # "Addictive Drums 2 - Funk" in Addictive Drums 2's own file
    middle = f" - {part}" if part else ""
    again = f" ({n})" if n else ""
    return safe_file_name(f"{p.name}{middle} {p.kind}{by}{again}") + ".RPL"


def rpl_fx_name(head: str, fallback: str) -> str:
    m = re.match(r'<VST "([^"]+)"', head)
    return m.group(1) if m else fallback


def allow_folders(copy_dir: str = portable.COPY_DIR, events=None) -> list[tuple[str, bool]]:
    """Open each protected folder from the checking copy, so macOS asks about them all now,
    while the person expects it, instead of in the middle of a run."""
    events = events or (lambda *a: None)
    out = []
    s = portable.Session(copy_dir)
    try:
        for d in portable.protected_folders():
            events("folder", d)
            try:
                lines = s.run("TOUCH\t" + d, quiet_limit=300)
                out.append((d, any(l.startswith("OK") for l in lines)))
            except portable.CheckerError:
                out.append((d, False))
    finally:
        s.stop()
    return out


def scan_new(copy_dir: str = portable.COPY_DIR, events=None, log=None) -> tuple[list[str], list[str]]:
    """Have the checking copy scan the plug-ins your REAPER hasn't scanned yet (installed since
    it last started), so their presets can be offered. Your REAPER's own plug-in list is never
    written: the copy keeps what it found in its own. Returns (scanned, not scanned), plug-in
    file names without .vst3; a plug-in that didn't answer the copy is in the second list."""
    events = events or (lambda *a: None)
    new = inventory.unscanned_files(checker=copy_dir)
    if not new:
        return [], []
    s = portable.Session(copy_dir, log=log, on_scan=lambda names: events("scanning", names))
    try:
        s.start()
    finally:
        s.stop()
    left = set(inventory.unscanned_files(checker=copy_dir))
    name = lambda f: os.path.splitext(os.path.basename(f))[0]   # noqa: E731
    return [name(f) for f in new if f not in left], [name(f) for f in new if f in left]


def scanning_words(names: list[str]) -> str:
    n = len(names)
    return (f"The checking copy of REAPER is scanning {n} plug-in{'s' if n != 1 else ''} your REAPER hasn't "
            f"scanned yet: {', '.join(names)}. Big instruments can take a minute or more each."
            + ("" if portable.WIN else " If macOS asks whether REAPER for checking presets can open a folder, "
               "choose Allow; scanning carries on by itself."))


def scan_new_words(done: list[str], left: list[str]) -> str:
    out = []
    if done:
        out.append(f"Scanned {', '.join(done)}. Their presets are offered now; libraries made for them work in "
                   "your REAPER once it has scanned them too (it does that when it next starts).")
    if left:
        out.append(f"{', '.join(left)} didn't answer the checking copy, so {'it' if len(left) == 1 else 'they'} "
                   "can't be offered yet. A plug-in waiting on its own activation or content does this; "
                   "open it once in REAPER, then try again.")
    return " ".join(out)


def unscanned_words(names: list[str], how: str = "File, Scan New Plug-ins") -> str:
    n = len(names)
    return (f"{n} plug-in{'s' if n != 1 else ''} your REAPER hasn't scanned yet, so {'its' if n == 1 else 'their'} "
            f"presets aren't offered: {', '.join(names)}. {how} has the checking copy of REAPER "
            "scan them; your REAPER isn't changed.")


class Builder:
    def __init__(self, outdir: str, author: str = "", min_keep: int = 5, check_twice: bool = True, split_over: int = 0,
                 copy_dir: str = portable.COPY_DIR, events=None, stop=None, log=None, prefix: bool = True,
                 per_category: bool = False, layout: str = "plugin"):
        self.outdir = outdir
        self.prefix = prefix               # "Category - Name", so REAPER's one list keeps categories together
        self.per_category = per_category   # one library per category, whatever the size
        self.layout = layout if layout in organize.LAYOUTS else "plugin"
        self._other = organize.OTHER_FOLDERS
        self.author = author
        self.min_keep = min_keep
        self.check_twice = check_twice
        self.split_over = split_over   # 0: never split
        self.written: set = set()
        self.copy_dir = copy_dir
        self.events = events or (lambda *a: None)
        self._stop = stop or (lambda: False)
        self.log = log or (lambda s: None)
        self.session = None

    # -- the checking copy --------------------------------------------------------------
    def _session(self):
        if self.stopped():
            raise StopIteration
        if self.session is None:
            self.session = portable.Session(self.copy_dir, log=self.log,
                                            on_scan=lambda names: self.events("scanning", names))
        return self.session

    def close(self):
        if self.session:
            self.session.stop()
            self.session = None

    BATCH = 500   # presets per preset file the copy loads: a 26,000-preset set never sits in one

    def _verify(self, fx: str, ini_file: str, presets: list, label: str, plugin=None, settle: float = 0) -> dict:
        """Load every preset in the checking copy, BATCH at a time.
        Returns {index: P line or 'CRASH:why'}, indexes counted across all batches."""
        got = {}
        for off in range(0, len(presets), self.BATCH):
            got.update(self._verify_batch(fx, ini_file, presets[off:off + self.BATCH], off, len(presets),
                                          label, plugin, settle))
        return got

    def _verify_batch(self, fx, ini_file, presets, off, total, label, plugin, settle: float = 0) -> dict:
        s = self._session()
        s.write_presets(ini_file, states.ini_text(presets))
        n = len(presets)
        got = {}
        count = [None]

        def on_line(l):
            if l.startswith("COUNT\t"):
                count[0] = int(l.split("\t")[1])
            elif l.startswith("P\t"):
                parts = l.split("\t", 6)
                k = int(parts[1])
                if off:   # say the index across the whole library, as judge() expects
                    if parts[3] == parts[1]:
                        parts[3] = str(k + off)
                    parts[1] = str(k + off)
                    l = "\t".join(parts)
                got[k] = l
                self.events("preset", label, k + 1 + off, total)
            elif l == "ADDFAIL":
                count[0] = -1
        start, troubles = 0, 0
        while start < n:
            if self.stopped():
                raise StopIteration
            try:
                s.run(f"VERIFY\t{fx}\t{n}\t{start}" + (f"\t{settle:g}" if settle else ""), quiet_limit=240,
                      on_line=on_line,
                      on_wait=lambda: self.events("waiting", plugin, portable.WAITING_WORDS), wait_after=15)
                break
            except portable.CheckerError as e:
                if str(e) == "stopped" or self.stopped():
                    raise StopIteration
                if count[0] is None or count[0] == -1:
                    raise portable.CheckerError("the plug-in wouldn't load" if count[0] == -1 else
                                                "REAPER went down loading the plug-in")
                bad = max([k for k in got if k >= start], default=start - 1) + 1
                got[bad] = "CRASH:" + ("REAPER went down loading it" if str(e) == "crashed"
                                       else "REAPER stopped responding while loading it")
                troubles += 1
                if troubles > 5:
                    raise portable.CheckerError("REAPER kept going down on this plug-in's presets")
                start = bad + 1
        if count[0] == -1:
            raise portable.CheckerError("the plug-in wouldn't load")
        if count[0] is not None and count[0] < n:
            for k in range(count[0], n):
                got.setdefault(k, "CRASH:REAPER didn't list it")
        return {k + off: v for k, v in got.items()}

    # -- one plug-in ----------------------------------------------------------------------
    def build_one(self, p: Plugin) -> Result:
        t0 = time.time()
        r = Result(p)
        fmt, found = p.best()
        r.fmt = fmt
        if not found:
            r.status, r.note = "failed", "No preset files were found for it."
            return r
        s = self._session()
        self.events("phase", p, "Loading the plug-in")
        try:
            cap = s.capture(p.fx, on_wait=lambda: self.events("waiting", p, portable.WAITING_WORDS))
        except portable.CheckerError as e:
            if str(e) == "stopped" or self.stopped():
                raise StopIteration
            r.status = "failed"
            r.note = {"addfail": "REAPER couldn't load the plug-in.",
                      "crashed": "The plug-in took REAPER down as it loaded.",
                      "stuck": STUCK_WORDS}.get(str(e), str(e))
            return r
        try:
            default = states.parse_state(states.chunk_state(cap.get("STATE", "").split("|")))
        except ValueError:
            r.status, r.note = "failed", "REAPER's saved state for this plug-in couldn't be read."
            return r
        fx_name = rpl_fx_name(cap.get("HEAD", ""), p.fx)
        ini_file = cap.get("FILE") or ""
        default_pv = cap.get("PV", "")
        if not ini_file:
            r.status, r.note = "failed", "REAPER didn't say where this plug-in keeps its presets."
            return r

        # 2. the presets
        self.events("phase", p, "Reading preset files")
        self._other = organize.OTHER_FOLDERS if organize.source(found) == "folders" else organize.OTHER
        presets, groups, r.unreadable = self._presets(found, default)
        if len(presets) == 1:
            r.status = "failed"
            r.note = f"None of its {len(found)} preset files could be made into REAPER presets."
            return r

        # 3. check every one
        try:
            got = self._verify(p.fx, ini_file, presets, "Checking", p)
        except portable.CheckerError as e:
            if str(e) == "stopped" or self.stopped():
                raise StopIteration
            r.status, r.note = "failed", str(e)[:1].upper() + str(e)[1:] + "."
            return r
        verdicts = self._judge_all(presets, got, default, default_pv)
        settle = 0.0
        if sum(v.ok for v in verdicts[1:]) < 0.5 * (len(presets) - 1):
            # Some plug-ins apply a preset on their own timer, a moment after it's chosen
            # (IK Multimedia's Hammond B-3X), so read straight away they still hold the last
            # one. Try a few again with time to settle; if that's what was wrong, check them all
            # that way (slower: SETTLE seconds a preset).
            try:
                better = self._settled(p, found, presets, verdicts)
            except portable.CheckerError as e:
                if str(e) == "stopped" or self.stopped():
                    raise StopIteration
                better = None
            if better:
                settle, cap, default, default_pv, presets, groups, r.unreadable, got, verdicts = better
        how = {pr[0]: v.how for pr, v in zip(presets, verdicts) if v.ok}
        kept = [pr for pr, v in zip(presets[1:], verdicts[1:]) if v.ok]
        r.cut = [(pr[0], v.why) for pr, v in zip(presets[1:], verdicts[1:]) if not v.ok]
        got1 = {presets[k][0]: got_comp(l) for k, l in got.items()}

        # 4. one library, or one per folder for a big set; each checked again as the finished file
        parts = self._parts(kept, groups)
        r.split = len(parts) > 1
        steady = False   # known only once the default preset has been saved twice
        for n_part, (label, items) in enumerate(parts):
            lib = ([presets[0]] if n_part == 0 else []) + items
            if self.check_twice and len(items) >= self.min_keep:
                try:
                    got2 = self._verify(p.fx, ini_file, lib, "Checking again", p, settle)
                except portable.CheckerError as e:
                    if str(e) == "stopped" or self.stopped():
                        raise StopIteration
                    r.status, r.note = "failed", "On the second check: " + str(e) + "."
                    return r
                v2 = self._judge_all(lib, got2, default, default_pv)
                # opaque states: the plug-in must save the same thing both times, unless it
                # doesn't even do that for its own defaults (some write a fresh id every time)
                if n_part == 0:
                    first = got1.get(presets[0][0])
                    steady = first is not None and got_comp(got2.get(0)) == first
                again = [lib[0]] if n_part == 0 else []
                for k, ((name, data), v) in enumerate(zip(lib, v2)):
                    if n_part == 0 and k == 0:
                        continue
                    if v.ok and how.get(name) == "controls" and steady and got1.get(name) is not None \
                            and got_comp(got2.get(k)) != got1[name]:
                        v = compare.Verdict(False, why="the plug-in saved it differently the second time")
                    if v.ok:
                        again.append((name, data))
                    else:
                        r.cut.append((name, "worked the first time, not the second: " + v.why))
                lib = again
            items = lib[1:] if n_part == 0 else lib
            if len(items) < self.min_keep:
                if items:
                    r.small.append((label, len(items)))
                continue
            sub = organize.library_dir(self.outdir, p.vendor, p.name, self.layout)
            os.makedirs(sub, exist_ok=True)
            path = os.path.join(sub, file_name(p, self.author, label))
            k = 2
            while path in self.written:   # two plug-ins in one run must never share a file
                path = os.path.join(sub, file_name(p, self.author, label, k))
                k += 1
            self.written.add(path)
            with open(path, "w", encoding="utf-8") as f:
                f.write(states.rpl_text(fx_name, lib))
            r.files.append((path, len(items)))
            r.kept += [(n, how.get(n, "")) for n, _ in items]
        r.seconds = time.time() - t0

        # 5. say what happened
        r.file = r.files[0][0] if r.files else None
        if r.files:
            r.status = "made"
            return r
        r.status = "dropped"
        working = r.tried - len(r.cut)
        if working == 0 and r.cut:
            r.note = f"None of its {r.tried} presets loaded."
        elif r.split or r.small:
            r.note = (f"{working} of its {r.tried} presets work, but no folder or category of them has the "
                      f"{self.min_keep} a library needs.")
        else:
            r.note = (f"Only {working} of its {r.tried} presets work, fewer than the "
                      f"{self.min_keep} a library needs." if r.tried else "No presets to check.")
        return r

    SETTLE = 1.0   # seconds a plug-in that applies presets on a timer gets for each one (Hammond B-3X needs ~1)
    SAMPLE = 8     # presets tried again with time to settle, to see whether it helps

    def _presets(self, found, default):
        """The REAPER presets for these files, given the plug-in's default state: the list
        ("0 Default settings" first), each one's group, and the files that couldn't be used."""
        cands, unreadable = [], []
        for fd, name, group in zip(found, preset_names(found, self.prefix), preset_groups(found)):
            try:
                comp, ctrl = formats.make_state(fd, default)
                cands.append((name, comp, ctrl, group))
            except Exception as e:  # noqa: BLE001
                unreadable.append((fd.path, str(e) or "couldn't be read"))
        cands.sort(key=lambda c: c[0].lower())
        names = states.unique_names([DEFAULT_NAME] + [c[0] for c in cands])
        presets = [(names[0], states.payload(default, default["comp"], names[0], default["ctrl"]))]
        groups = {}
        for name, (_, comp, ctrl, group) in zip(names[1:], cands):
            presets.append((name, states.payload(default, comp, name, ctrl)))
            groups[name] = group
        return presets, groups, unreadable

    def _settled(self, p, found, presets, verdicts):
        """Most presets failed when read back at once. Capture the default again and try a
        sample with SETTLE seconds each; when clearly more of them pass, check the whole set
        that way. Returns everything build_one needs from the better run, or None."""
        s = self._session()
        self.events("phase", p, "Giving the plug-in a moment to apply each preset")
        cap = s.capture(p.fx, settle=self.SETTLE)
        try:
            default = states.parse_state(states.chunk_state(cap.get("STATE", "").split("|")))
        except ValueError:
            return None
        ini_file, default_pv = cap.get("FILE") or "", cap.get("PV", "")
        if not ini_file:
            return None
        new, groups, unreadable = self._presets(found, default)
        if len(new) != len(presets):
            return None
        sample = new[:1 + self.SAMPLE]
        got = self._verify(p.fx, ini_file, sample, "Trying with time to settle", p, self.SETTLE)
        tried = self._judge_all(sample, got, default, default_pv)
        before = sum(v.ok for v in verdicts[1:len(sample)])
        after = sum(v.ok for v in tried[1:])
        self.log(f"{p.name}: {before} of {len(sample) - 1} passed at once, {after} with {self.SETTLE:g}s to settle")
        if after <= before or after < 0.5 * (len(sample) - 1):
            return None
        got = self._verify(p.fx, ini_file, new, "Checking", p, self.SETTLE)
        return (self.SETTLE, cap, default, default_pv, new, groups, unreadable, got,
                self._judge_all(new, got, default, default_pv))

    def _judge_all(self, presets, got, default, default_pv):
        verdicts = []
        for k, (name, data) in enumerate(presets):
            line = got.get(k)
            if line and line.startswith("CRASH:"):
                verdicts.append(compare.Verdict(False, why=line[6:]))
            else:
                verdicts.append(compare.judge(name, k, data, line, default, default_pv))
        # A stronger check where the state can't be read: presets from different files that
        # leave the plug-in in exactly the same state, controls and all, are one sound. The
        # first is kept; the others are left out as the same, not passed on as different.
        seen = {}
        for k, ((name, data), v) in enumerate(zip(presets, verdicts)):
            if not (v.ok and v.how == "controls") or k == 0:
                continue
            line = got.get(k)
            sig = (got_comp(line), line.split("\t")[5] if line else None)
            src = states.parse_state(data)["comp"]
            if sig in seen and seen[sig][1] != src:
                verdicts[k] = compare.Verdict(False, why=f"the plug-in ends up exactly as it does for "
                                                         f"{seen[sig][0]}, though the files differ")
            else:
                seen.setdefault(sig, (name, src))
        return verdicts

    def _parts(self, kept, groups):
        """[(label or None, presets)]: one library, or one per category (a top folder, or the
        category in the files) when a plug-in has more presets than split_over, or always when
        per_category is on, and they fall in more than one."""
        other = getattr(self, "_other", organize.OTHER_FOLDERS)
        labels = {groups.get(n, "") for n, _ in kept}
        big = self.split_over and len(kept) > self.split_over
        if not (big or self.per_category) or len(labels) < 2:
            return [(None, kept)]
        by = {}
        for pr in kept:
            by.setdefault(groups.get(pr[0], "") or other, []).append(pr)
        # categories too small for a library of their own go together rather than being lost
        small = [k for k, v in by.items() if len(v) < self.min_keep]
        if len(small) > 1 or (small and other in by and small != [other]):
            merged = []
            for k in small:
                merged += by.pop(k)
            by.setdefault(other, []).extend(merged)
        return sorted(by.items(), key=lambda x: (x[0] == other, x[0].lower()))

    def abort(self):
        """Stop now, from any thread: the copy is ended and nothing starts it again. Libraries
        already written are kept; the plug-in being checked is reported as stopped."""
        self._aborted = True
        if self.session:
            self.session.close()

    def stopped(self) -> bool:
        return getattr(self, "_aborted", False) or self._stop()

    def build(self, plugs: list[Plugin]) -> list[Result]:
        """Raises portable.CheckerError before starting when it can't run at all: another run
        holds the checking copy, or the libraries folder can't be written to."""
        os.makedirs(os.path.dirname(portable.LOCK), exist_ok=True)
        lock = open(portable.LOCK, "a+")
        try:
            if portable.WIN:
                import msvcrt
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lock.close()
            raise portable.CheckerError("Libraries are already being made, in another window or from the "
                                        "command line. One run at a time can use the checking copy of REAPER.")
        try:
            try:
                os.makedirs(self.outdir, exist_ok=True)
                probe = os.path.join(self.outdir, ".write-test")
                with open(probe, "w") as f:
                    f.write("")
                os.remove(probe)
            except OSError:
                from . import access
                raise portable.CheckerError(
                    f"Libraries can't be saved in {self.outdir}: that folder can't be written to. "
                    + (access.CFA_STEPS if access.ransomware_protection() == "on" else "Choose another in Preferences."))
            return self._build(plugs)
        finally:
            lock.close()

    def _build(self, plugs: list[Plugin]) -> list[Result]:
        results = []
        try:
            for i, p in enumerate(plugs):
                if self.stopped():
                    results += [Result(q, status="skipped") for q in plugs[i:]]
                    break
                self.events("plugin", p, i + 1, len(plugs))
                try:
                    r = self.build_one(p)
                except StopIteration:
                    results.append(Result(p, status="stopped"))
                    results += [Result(q, status="skipped") for q in plugs[i + 1:]]
                    break
                results.append(r)
                self.events("result", r)
        finally:
            self.close()
        return results


# ---- the report -----------------------------------------------------------------------------

IMPORT_STEPS = """How to use a library in REAPER

1. Put the plug-in on a track, so its FX window is open.
2. Open the FX window's preset menu: the button named Presets and Performance
   Management (with OSARA, Tab to it, then press Shift+Space).
3. Choose Import preset library, and pick the .RPL file.
4. The presets are now in the plug-in's preset list, on every track. Each library
   starts with "0 Default settings", the plug-in as it loads fresh.
"""


def report_text(results: list[Result], outdir: str, when: datetime.datetime | None = None) -> str:
    when = when or datetime.datetime.now()
    made = [r for r in results if r.status == "made"]
    other = [r for r in results if r.status != "made"]
    # spelled out by hand: %-d and %-I don't exist on Windows, where they stop the report
    hour = when.hour % 12 or 12
    L = [f"Preset libraries made {when:%A} {when.day} {when:%B %Y} at {hour}:{when:%M %p}", ""]
    total = sum(len(r.kept) for r in made)
    n_files = sum(len(r.files) for r in made)
    L.append(f"{n_files} {'library' if n_files == 1 else 'libraries'} made for {len(made)} of "
             f"{len(results)} plug-in{'' if len(results) == 1 else 's'}, {total} working presets in all.")
    L.append(f"Saved in {outdir}")
    L.append("")
    L.append("Every preset here was loaded by name in a separate copy of REAPER, and the plug-in's")
    L.append("own saved settings were compared with the preset file. Presets that didn't come back")
    L.append("the same were left out. A library is checked twice, the second time as the finished file.")
    L.append("")
    for r in made:
        L.append(r.sentence())
        for path, n in r.files:
            L.append(f"  File: {os.path.relpath(path, outdir)}, {n} presets")
        for label, n in r.small:
            L.append(f"  Not made: {label}, only {n} working, fewer than a library needs.")
        hows = {}
        for _n, h in r.kept:
            hows[h] = hows.get(h, 0) + 1
        for h, n in sorted(hows.items(), key=lambda x: -x[1]):
            L.append(f"  {n} {compare.HOW_WORDS.get(h, h)}.")
        L += ["  " + x for x in reason_lines(r.cut, limit_names=1000)]
        for path, why in r.unreadable[:10]:
            L.append(f"  Couldn't read {os.path.basename(path)}: {why}.")
        if len(r.unreadable) > 10:
            L.append(f"  ... and {len(r.unreadable) - 10} more files couldn't be read.")
        L.append("")
    for r in other:
        L.append(r.sentence())
        L += ["  " + x for x in reason_lines(r.cut, limit_names=1000)]
        if r.unreadable and not r.cut:
            L.append(f"  {len(r.unreadable)} files couldn't be read, for example "
                     f"{os.path.basename(r.unreadable[0][0])}: {r.unreadable[0][1]}.")
        L.append("")
    L.append(IMPORT_STEPS)
    return "\n".join(L)


def write_report(results: list[Result], outdir: str) -> str:
    os.makedirs(outdir, exist_ok=True)
    now = datetime.datetime.now()
    path = os.path.join(outdir, f"Report {now:%Y-%m-%d %H.%M.%S}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(report_text(results, outdir, now))
    with open(os.path.join(outdir, "How to import.txt"), "w", encoding="utf-8") as f:
        f.write(IMPORT_STEPS)
    data = [dict(plugin=r.plugin.fx, status=r.status, file=r.file, files=r.files, small=r.small, kept=r.kept, cut=r.cut,
                 unreadable=r.unreadable, note=r.note, format=r.fmt, seconds=round(r.seconds, 1)) for r in results]
    with open(path[:-4] + ".json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    return path
