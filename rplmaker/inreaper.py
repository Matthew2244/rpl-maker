"""Which plug-ins already have their presets in REAPER: the person made them by hand, or
imported a library before. Read only: REAPER's files are never written.

REAPER keeps each plug-in's own presets in its resource folder's presets folder, one .ini per
plug-in and format: "vst3-<file name>.ini", "vst-<file name>.ini", "au-<Maker>: <Name>.ini",
"clap-<id>.ini". Files ending "-builtin.ini" are REAPER's cache of a plug-in's factory list,
not anyone's work, and are skipped; so are JSFX ("js-").

Almost every plug-in gets one of these files the first time it's used, often holding only a
default or a blank entry. So a file existing, or holding a preset or two, means nothing. A
plug-in counts as already done only when REAPER's file for it holds, by name, at least half of
the distinct preset names found for it here, and at least 3 of them. Entries called Default,
Init, Untitled, "Program 3" and the like, or with no name, are never counted, on either side.
A name is matched ignoring case, spaces and punctuation, and a name saved as "Folder - Name"
(how this app names presets in folders) matches "Name".
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass

from . import APP_NAME, inventory

PRESETS = "presets"
WORDS = {"vst3": "VST3", "vst": "VST2", "au": "AU", "clap": "CLAP"}
MIN_MATCHED = 3
SHARE = 0.5

_PLACEHOLDER = re.compile(r"\d*(default|defaults|defaultsettings|defaultpreset|factorydefault|init|initial|"
                          r"initpatch|initpreset|untitled|program|preset)?\d*")


@dataclass
class InReaper:
    file: str          # the .ini's own name, as REAPER wrote it
    fmt: str           # "vst3", "vst", "au", "clap"
    named: int         # real preset names in it (not Default, Init, blank and the like)
    matched: int       # how many of the names found here it holds
    of: int            # distinct real names found here

    @property
    def done(self) -> bool:
        return self.matched >= needed(self.of)

    @property
    def fmt_words(self) -> str:
        return WORDS.get(self.fmt, self.fmt.upper())


def needed(of: int) -> int:
    """How many of the names found here REAPER's file must hold to count as done."""
    return max(MIN_MATCHED, math.ceil(of * SHARE))


def key(name: str) -> str:
    return inventory.norm(name)


def placeholder(name: str) -> bool:
    """Default, Init, Untitled, Program 1, 0 Default settings, a blank name..."""
    k = key(name)
    return not k or bool(_PLACEHOLDER.fullmatch(k))


def names_in(path: str) -> list[str]:
    """The preset names in one of REAPER's presets .ini files, in order."""
    out, in_preset = [], False
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("["):
                    in_preset = line.strip().lower().startswith("[preset")
                elif in_preset and line.startswith("Name="):
                    out.append(line[5:].rstrip("\r\n"))
    except OSError:
        pass
    return out


def name_keys(names: list[str]) -> set[str]:
    """Every way a saved name can match a found one: whole, and what follows each " - " or "/"
    in it, since this app saves presets in folders as "Folder - Sub - Name" and a preset's own
    name can hold " - " too ("BA Bus - Gentle")."""
    out = set()
    for n in names:
        if placeholder(n):
            continue
        out.add(key(n))
        for sep in (" - ", "/"):
            parts = n.split(sep)
            for i in range(1, len(parts)):
                tail = sep.join(parts[i:])
                if not placeholder(tail):
                    out.add(key(tail))
    return out


# -- what REAPER calls each plug-in, from its own scan caches (read, never written) -----------

def vst2_cache(resource: str) -> dict[str, list[tuple[int | None, str]]]:
    """VST2 plug-ins in REAPER's plug-in list: key(file stem) -> [(unique id, display name)]."""
    out: dict = {}
    path = inventory.cache_file(resource)
    if not path:
        return out
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r"^(.+?)\.(vst|dll|vst\.dylib|so)=[^,]*,(-?\d+)?[^,]*,(.*)$", line.rstrip("\r\n"), re.I)
                if not m:
                    continue
                uid = int(m.group(3)) if m.group(3) else None
                out.setdefault(key(m.group(1)), []).append((uid, m.group(4).split("!!!")[0]))
    except OSError:
        pass
    return out


def clap_cache(resource: str) -> dict[str, list[str]]:
    """CLAP plug-ins in REAPER's lists: key(plug-in id) and key(file stem) -> [display name]."""
    out: dict = {}
    try:
        files = [f for f in os.listdir(resource) if f.lower().startswith("reaper-clap-") and f.lower().endswith(".ini")]
    except OSError:
        return out
    for fn in files:
        try:
            with open(os.path.join(resource, fn), encoding="utf-8", errors="replace") as f:
                stem = ""
                for line in f:
                    line = line.rstrip("\r\n")
                    if line.startswith("["):
                        stem = re.sub(r"\.clap$", "", line.strip("[]"), flags=re.I)
                    elif "=" in line and not line.startswith("_="):
                        cid, _, rest = line.partition("=")
                        display = rest.split("|", 1)[-1].split("!!!")[0]
                        out.setdefault(key(cid), []).append(display)
                        if stem:
                            out.setdefault(key(stem), []).append(display)
        except OSError:
            pass
    return out


def _same_maker(a: str, b: str) -> bool:
    a, b = key(a), key(b)
    return not a or not b or a in b or b in a


def _names_it(p, display: str) -> bool:
    name, vendor = inventory.split_display(display)
    return key(name) == key(p.name) and _same_maker(vendor, p.vendor)


def is_for(p, fmt: str, rest: str, vst2: dict, clap: dict) -> bool:
    """Is REAPER's presets file "<fmt>-<rest>.ini" this plug-in's, in any format?"""
    if fmt == "vst3":
        bundle = re.sub(r"\.vst3$", "", p.bundle or "", flags=re.I)
        return key(rest) in {key(bundle), key(p.name)} - {""}
    if fmt == "vst":
        known = vst2.get(key(rest))
        if known:
            want = int(p.vst2, 16) if p.vst2 else None
            return any((want is not None and uid == want) or _names_it(p, d) for uid, d in known)
        return key(rest) == key(p.name)
    if fmt == "au":
        maker, sep, name = rest.partition(": ")
        if not sep:
            maker, name = "", rest
        return key(name) == key(p.name) and _same_maker(maker, p.vendor)
    if fmt == "clap":
        known = clap.get(key(rest))
        if known:
            return any(_names_it(p, d) for d in known)
        return key(rest) == key(p.name) or key(rest.rsplit(".", 1)[-1]) == key(p.name)
    return False


def presets_files(resource: str) -> list[tuple[str, str, str]]:
    """(path, format, the rest of the name) for each presets .ini that could be someone's work."""
    folder = os.path.join(resource, PRESETS)
    out = []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return out
    for fn in names:
        stem, ext = os.path.splitext(fn)
        if ext.lower() != ".ini" or stem.lower().endswith("-builtin"):
            continue
        fmt, sep, rest = stem.partition("-")
        if sep and fmt.lower() in WORDS:
            out.append((os.path.join(folder, fn), fmt.lower(), rest))
    return out


def check(p, files, vst2, clap) -> InReaper | None:
    """The best evidence REAPER has this plug-in's presets: a file that counts as done, the
    plug-in's own format first; else the closest file, for the details. None when REAPER has
    no presets file for it with any real names."""
    _fmt, found = p.best()
    wanted = {key(f.name) for f in found if not placeholder(f.name)}
    if not wanted:
        return None
    best = None
    for path, fmt, rest in files:
        if not is_for(p, fmt, rest, vst2, clap):
            continue
        names = [n for n in names_in(path) if not placeholder(n)]
        if not names:
            continue
        r = InReaper(os.path.basename(path), fmt, len(names), len(wanted & name_keys(names)), len(wanted))
        rank = (r.done, fmt == "vst3", r.matched)
        if best is None or rank > best[0]:
            best = (rank, r)
    return best[1] if best else None


def mark(plugs, resource: str = inventory.REAPER_RESOURCE) -> None:
    """Set .in_reaper on every plug-in that has presets found for it. Never raises: this is
    a courtesy, and a scan must never fail because of it."""
    try:
        files = presets_files(resource)
        if not files:
            return
        vst2, clap = vst2_cache(resource), clap_cache(resource)
        for p in plugs:
            if p.count:
                p.in_reaper = check(p, files, vst2, clap)
    except Exception:  # noqa: BLE001
        pass


# -- what's said about it --------------------------------------------------------------------

def done_of(p) -> InReaper | None:
    r = getattr(p, "in_reaper", None)
    return r if r is not None and r.done else None


def status_words(r: InReaper) -> str:
    """The start of a row, said first: "Already in REAPER"."""
    return "Already in REAPER" if r.fmt == "vst3" else f"Already in REAPER for the {r.fmt_words} version"


def detail_lines(r: InReaper | None) -> list[str]:
    if r is None:
        return []
    has = (f"its presets in REAPER, for the {r.fmt_words} version ({r.file}), hold {r.named} "
           f"preset{'' if r.named == 1 else 's'}, including {r.matched} of the {r.of} preset names found here")
    if not r.done:
        if not r.matched:
            return []
        return [f"{has[0].upper()}{has[1:]}. That's fewer than {needed(r.of)}, so it isn't counted as already in REAPER."]
    out = [f"Already in REAPER: {has}. {APP_NAME} doesn't check it for you; check it to make a library anyway."]
    if r.fmt != "vst3":
        out.append(f"Those load in the {r.fmt_words} version only; a library made here is for the VST3 version.")
    return out
