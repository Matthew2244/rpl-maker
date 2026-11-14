"""Which plug-ins are installed, and which of them have preset files this can read.

Plug-ins come from REAPER's own plug-in list (its scan cache), read and never written: the
names there are the names REAPER will look the plug-in up by. Preset files are found by
walking the places vendors install them, and matched to a plug-in by the VST3 class id inside
the file when there is one, else the VST2 id (VST3 plug-ins that grew from VST2 ones carry it
in their class id), else by folder name.
"""
from __future__ import annotations

import dataclasses
import sys
import json
import os
import platform
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field

from . import formats

HOME = os.path.expanduser("~")
WIN = sys.platform == "win32"
APPDATA = os.environ.get("APPDATA") or os.path.join(HOME, "AppData", "Roaming")
# This app's own folder: settings, the scan cache, the checking copy of REAPER
SUPPORT = (os.path.join(APPDATA, "RPL Maker") if WIN
           else os.path.join(HOME, "Library", "Application Support", "RPL Maker"))
CACHE = os.path.join(SUPPORT, "scan-cache.json")
CACHE_VERSION = 1
REAPER_RESOURCE = (os.path.join(APPDATA, "REAPER") if WIN
                   else os.path.join(HOME, "Library", "Application Support", "REAPER"))

# Where vendors put factory presets. Extra folders come from Settings.
if WIN:
    _pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    _pd = os.environ.get("ProgramData", r"C:\ProgramData")
    _pub = os.environ.get("PUBLIC", r"C:\Users\Public")
    SEARCH_ROOTS = [
        os.path.join(HOME, "Documents", "VST3 Presets"),       # the VST3 standard, per person
        os.path.join(_pd, "VST3 Presets"),                    # and for everyone
        _pd,                                                  # where makers keep factory content
        os.path.join(_pf, "Common Files"),                    # VST3 bundles and some makers' content
        os.path.join(_pub, "Documents"),
        os.path.join(HOME, "Documents", "Native Instruments", "User Content"),
    ]
else:
    SEARCH_ROOTS = [
        "/Library/Audio/Presets",
        os.path.join(HOME, "Library", "Audio", "Presets"),
        "/Library/Application Support",
        "/Users/Shared",
        os.path.join(HOME, "Documents", "Native Instruments", "User Content"),
        "/Library/Audio/Plug-Ins/VST3",
        os.path.join(HOME, "Library", "Audio", "Plug-Ins", "VST3"),
    ]
# Big folders under /Library/Application Support that never hold plug-in presets.
SKIP_DIRS = {"Microsoft", "Windows", "Package Cache", "WindowsApps", "Packages", "regid.1991-06.com.microsoft",
             "Apple", "Google", "Microsoft", "com.apple.TCC", "ApplePushService", "CrashReporter",
             "Adobe", "Mozilla", "Zoom", "Logitech", "Steam", "MacUpdater", "Script Editor",
             "Avid", ".Trashes", "node_modules", ".git", "Samples", "Sample Libraries"}


@dataclass
class Plugin:
    fx: str                  # what REAPER calls it: "VST3: Ozone 12 Equalizer (iZotope)"
    name: str                # "Ozone 12 Equalizer"
    vendor: str
    class_id: str
    bundle: str              # file name in REAPER's cache, e.g. Ozone_12_Equalizer.vst3
    instrument: bool
    presets: dict = field(default_factory=dict)   # format -> [Found]

    @property
    def vst2(self) -> str | None:
        """The VST2 id inside a VST2-compatible class id ("VST" + id + name)."""
        if self.class_id.startswith("565354"):
            return self.class_id[6:14]
        return None

    def best(self) -> tuple[str, list] | tuple[None, list]:
        for f in formats.FORMATS:
            if self.presets.get(f):
                return f, self.presets[f]
        return None, []

    @property
    def count(self) -> int:
        return len(self.best()[1])

    @property
    def kind(self) -> str:
        return "VST3i" if self.instrument else "VST3"


def cache_file(resource: str = REAPER_RESOURCE) -> str | None:
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "64"
    for n in (f"reaper-vstplugins_{arch}.ini", "reaper-vstplugins64.ini", "reaper-vstplugins_arm64.ini",
              "reaper-vstplugins_arm64ec.ini"):
        p = os.path.join(resource, n)
        if os.path.exists(p):
            return p
    return None


def split_display(display: str) -> tuple[str, str]:
    """'Pianoteq 9 (Modartt) (1->16ch)' -> ('Pianoteq 9', 'Modartt'). From the end: channel
    counts and architectures are dropped, the next group is the maker, and anything before
    that stays in the name: 'Blue Cat's Gain 3 (Dual) (Blue Cat Audio)' keeps '(Dual)', or
    its Dual, Mono and Stereo libraries would all get the same file name. Maker groups can
    nest: 'UADx 1176 (Universal Audio (UADx))'."""
    s = display.strip()
    vendor = ""
    while s.endswith(")") and not vendor:
        depth, i = 0, len(s) - 1
        while i >= 0:
            if s[i] == ")":
                depth += 1
            elif s[i] == "(":
                depth -= 1
                if depth == 0:
                    break
            i -= 1
        if i <= 0:
            break
        g = s[i + 1:-1]
        s = s[:i].rstrip()
        if not re.fullmatch(r"\d+ ?(out|ch)|\d+->\d+ ?ch|x86_64|arm64", g, re.I):
            vendor = g
    return s or display, vendor


def plugins(resource: str = REAPER_RESOURCE) -> list[Plugin]:
    path = cache_file(resource)
    if not path:
        return []
    out, seen = [], set()
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = re.match(r"^(.+?\.vst3)=[^,]*,[^{,]*\{([0-9A-Fa-f]{32}),(.*)$", line.rstrip("\n"))
            if not m:
                continue
            bundle, cls, display = m.group(1), m.group(2).upper(), m.group(3)
            instrument = display.endswith("!!!VSTi")
            display = display.split("!!!")[0]
            if not display or cls in seen:
                continue
            seen.add(cls)
            name, vendor = split_display(display)
            out.append(Plugin(("VST3i: " if instrument else "VST3: ") + display, name, vendor, cls, bundle, instrument))
    out.sort(key=lambda p: (p.name.lower(), p.vendor.lower()))   # rows read name first, so sort by it
    return out


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def find_files(roots: list[str], progress=None, stop=None) -> list[str]:
    hits = []
    last = time.time()
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dp, dn, fn in os.walk(root):
            if stop and stop():
                return hits
            dn[:] = [d for d in dn if d not in SKIP_DIRS and not d.startswith(".")]
            # XML only counts inside a folder called Presets (or under Audio/Presets), never
            # anywhere else on the disk
            presety = "preset" in dp.lower()
            for f in fn:
                ext = os.path.splitext(f)[1].lower()
                fmt = formats.PRESET_EXTS.get(ext)
                if not fmt or (fmt == "xml" and not presety):
                    continue
                hits.append(os.path.join(dp, f))
            if progress and time.time() - last > 0.5:
                last = time.time()
                progress(len(hits), dp)
    return hits


def _load_cache(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d.get("files", {}) if d.get("version") == CACHE_VERSION else {}
    except (OSError, ValueError):
        return {}


def _save_cache(path, entries):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": CACHE_VERSION, "files": entries}, f)
        os.replace(tmp, path)
    except OSError:
        pass   # a cache that can't be written only costs time next launch


def read_all(files: list[str], progress=None, stop=None, cache_path: str | None = CACHE) -> list:
    """formats.read for every file, reusing what the last scan read when a file's size and
    modification time are unchanged. Reading is mostly waiting on the disk, so new files are
    read on several threads at once."""
    from concurrent.futures import ThreadPoolExecutor
    old = _load_cache(cache_path) if cache_path else {}
    out: list = [None] * len(files)
    todo, stamps = [], {}
    for i, path in enumerate(files):
        try:
            st = os.stat(path)
        except OSError:
            continue
        stamp = [st.st_size, int(st.st_mtime)]
        stamps[path] = stamp
        hit = old.get(path)
        if hit and hit[0] == stamp:
            out[i] = formats.Found(**hit[1]) if hit[1] else None
        else:
            todo.append(i)
    last, done = time.time(), len(files) - len(todo)
    with ThreadPoolExecutor(8) as pool:
        for i, fd in zip(todo, pool.map(lambda k: formats.read(files[k]), todo)):
            out[i] = fd
            done += 1
            if stop and stop():
                break
            if progress and time.time() - last > 0.5:
                last = time.time()
                progress(done, len(files))
    if cache_path:
        _save_cache(cache_path, {p: [stamps[p], dataclasses.asdict(fd) if fd else None]
                                 for p, fd in zip(files, out) if p in stamps})
    return out


def _same_bytes(a: str, b: str) -> bool:
    try:
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return fa.read() == fb.read()
    except OSError:
        return False


def match(plugs: list[Plugin], files: list[str], progress=None, stop=None, cache_path: str | None = CACHE) -> None:
    by_cls = {p.class_id: p for p in plugs}
    by_vst2 = defaultdict(list)
    for p in plugs:
        if p.vst2:
            by_vst2[p.vst2].append(p)
    by_name = defaultdict(list)
    for p in plugs:
        by_name[norm(p.name)].append(p)
        if p.vendor:
            by_name[norm(p.vendor + p.name)].append(p)
    # The same preset installed in two places (a library on two drives) counts once: same name,
    # same folder name, same bytes. A vendor filing one preset under two categories (LTL:
    # "04 Drums" and the artist's folder) is deliberate and kept.
    copies: dict = {}
    for path, fd in zip(files, read_all(files, progress, stop, cache_path)):
        if not fd:
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        targets = []
        if fd.class_id and fd.class_id in by_cls:
            targets = [by_cls[fd.class_id]]
        elif fd.vst2 and fd.vst2 in by_vst2:
            targets = by_vst2[fd.vst2][:1]
        elif not fd.class_id:  # no id matched: the folder it sits in may be named after the plug-in
            for part in reversed(fd.folder_hint or os.path.dirname(path).split(os.sep)[-4:]):
                if by_name.get(norm(part)):
                    targets = by_name[norm(part)][:1]
                    break
        for p in targets:
            key = (p.class_id, fd.fmt, fd.name, size, os.path.basename(os.path.dirname(path)))
            if key in copies and _same_bytes(copies[key], path):
                continue
            copies.setdefault(key, path)
            p.presets.setdefault(fd.fmt, []).append(fd)


def scan(extra_roots: list[str] | None = None, resource: str = REAPER_RESOURCE, progress=None, stop=None) -> list[Plugin]:
    """Every installed VST3 plug-in, with the preset files found for it."""
    plugs = plugins(resource)
    roots = SEARCH_ROOTS + [r for r in (extra_roots or []) if r]
    files = find_files(roots, (lambda n, d: progress("looking", n, d)) if progress else None, stop)
    match(plugs, files, (lambda k, n: progress("reading", k, n)) if progress else None, stop)
    return plugs
