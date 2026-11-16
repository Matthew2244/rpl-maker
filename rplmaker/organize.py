"""Keeping presets in order: the maker's own categories, names that sort into groups, and a
folder tree of libraries.

REAPER shows a plug-in's presets as one flat list, with no folders or submenus, and every
library imported for a plug-in lands in that same list. So inside REAPER the only way to keep
a category together is its name: "Bass - Deep Sub" sits beside "Bass - Round", away from
"Lead - Saw". On disk, and on a sharing site like the Hoard, a folder tree does the job:
Maker / Plug-in / library.RPL, with one library per category when that's wanted.

Categories come from the maker and nowhere else: the folders their preset files were
installed in, or the category written inside the file (an NKS preset's first sound type, a
VST3 preset's instrument category). Nothing is guessed from words in preset names, so a
preset is never put in a category its maker didn't give it. A preset with no category keeps
its name as it is.

This module also organizes libraries that already exist (`organize_folder`), for libraries
made before this was here, or made by someone else.
"""
from __future__ import annotations

import os
import re
import shutil
import unicodedata

from . import states

SEP = " - "
OTHER_FOLDERS = "Other folders"   # the presets of folders too small to be a library of their own
OTHER = "Other"                   # the presets with no category, when each category has its own library
DEFAULT = "0 Default settings"

LAYOUTS = {
    "plugin": "Maker, then plug-in",   # <out>/Plugin Alliance/bx_glue/bx_glue VST3 by Sam.RPL
    "maker": "Maker only",             # <out>/Plugin Alliance/bx_glue VST3 by Sam.RPL (before 0.2.0)
}

# ---- names every system can save ----------------------------------------------------------

_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
FOLDER_LIMIT = 64     # one folder's name, in characters
FILE_LIMIT = 120      # one file's name, without the extension
# Windows' usual limit is 260 characters for a whole path. A library made here may be copied
# into C:\Users\<name>\Downloads\<a zip's name>\ on someone's PC, so each part stays short:
# 64 + 64 + 120 leaves about half the limit for wherever it's copied to.


def safe_name(s: str, limit: int = FILE_LIMIT) -> str:
    """A file or folder name every system can save: none of the characters Windows refuses
    (a library made on a Mac may be copied to a PC), no control characters, no trailing dot or
    space, not one of the names Windows keeps for devices (CON, NUL, COM1...), not longer than
    `limit` characters, and in the composed Unicode form every system shows the same way."""
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", s).strip(" .")
    if len(s) > limit:
        s = s[:limit].rstrip(" .-")
    if s.split(".")[0].strip().upper() in _RESERVED:
        s += "_"
    return s or "Untitled"


def library_dir(outdir: str, vendor: str, plugin_name: str, layout: str = "plugin") -> str:
    """Where a plug-in's libraries go: the maker's folder, then (by default) the plug-in's."""
    d = os.path.join(outdir, safe_name(vendor or "Other", FOLDER_LIMIT))
    if layout == "plugin":
        d = os.path.join(d, safe_name(plugin_name, FOLDER_LIMIT))
    return d


# ---- categories ---------------------------------------------------------------------------

def rel_parts(paths: list[str]) -> list[list[str]]:
    """Each file's folders below the folder its install location's presets share. Files are
    first bucketed by install location (the first four parts of the path: ~/Documents/...,
    /Volumes/<drive>/..., /Library/...), so a library installed on two drives doesn't put
    'Users' or 'Volumes' in every name."""
    buckets: dict = {}
    for i, path in enumerate(paths):
        parts = os.path.normpath(os.path.dirname(path)).split(os.sep)
        buckets.setdefault(tuple(parts[:max(1, min(5, len(parts) - 2))]), []).append(i)
    out = [[] for _ in paths]
    for idx in buckets.values():
        dirs = [os.path.normpath(os.path.dirname(paths[i])) for i in idx]
        try:
            root = os.path.commonpath(dirs)
        except ValueError:
            root = ""
        for i, d in zip(idx, dirs):
            rel = os.path.relpath(d, root) if root else "."
            out[i] = [] if rel == "." else [p for p in rel.split(os.sep) if p]
    return out


def meta_categories(found: list) -> list[str]:
    """The category each file carries inside it, used only when it divides the set: at least
    two different ones among the plug-in's presets. One category on every preset (Ozone 12
    Equalizer's NKS presets are all "EQ") says nothing a name prefix would help with."""
    cats = [(getattr(f, "category", None) or "").strip() for f in found]
    return cats if len({c for c in cats if c}) >= 2 else ["" for _ in found]


def source(found: list) -> str:
    """Where the categories come from: 'folders', 'files' (metadata inside them) or ''."""
    if any(rel_parts([f.path for f in found])):
        return "folders"
    if any(meta_categories(found)):
        return "files"
    return ""


def categories(found: list) -> list[str]:
    """Each preset's category from its maker, '' for none. The folders the files were installed
    in come first ("Mixing / Drums" reads "Mixing - Drums"); when every file sits in one folder,
    the category inside the files."""
    rels = rel_parts([f.path for f in found])
    if any(rels):
        return [SEP.join(states.clean_name(p) for p in parts) for parts in rels]
    return meta_categories(found)


def prefixed(category: str, name: str) -> str:
    """'Category - Name', without saying the category twice: a name that already starts with
    it (or with any of its parts) keeps those words once."""
    name = states.clean_name(name)
    if not category:
        return name
    parts = [p for p in category.split(SEP) if p]
    keep = [p for p in parts if not starts_with(name, p)]
    return states.clean_name(SEP.join(keep + [name]))


def starts_with(name: str, word: str) -> bool:
    """Does the name already begin with this category word, as a word of its own: "Bass - Deep",
    "Bass-Deep", "Bass_Deep", "Bass: Deep" or just "Bass" do; "Bassline" doesn't."""
    n, w = name.lower(), word.lower().strip()
    return n == w or (n.startswith(w) and re.match(r"\s*[-_:/|]", n[len(w):]) is not None)


def preset_names(found: list, prefix: bool = True) -> list[str]:
    """Each preset's name in REAPER's list: the name its maker gave it, starting with its
    category when `prefix` is on."""
    if not prefix:
        return [states.clean_name(f.name) for f in found]
    return [prefixed(c, f.name) for f, c in zip(found, categories(found))]


def preset_groups(found: list) -> list[str]:
    """The category each preset's library is split by ('' for none): the top folder (an ADpak,
    a Pianoteq instrument, an artist's presets), or the category inside the file."""
    rels = rel_parts([f.path for f in found])
    if any(rels):
        first = {p[0] if p else "" for p in rels}
        if len(first) < 3 and any(len(p) > 1 for p in rels):
            # one or two wrappers above the real folders (Addictive Drums 2 and its [GM] twin
            # above the ADpaks): go one level deeper
            return [SEP.join(p[:2]) for p in rels]
        return [p[0] if p else "" for p in rels]
    return meta_categories(found)


def sort_key(name: str) -> tuple:
    """0 Default settings first, then by name, ignoring case: categories sort together."""
    return (name != DEFAULT, name.lower())


# ---- libraries that already exist ---------------------------------------------------------

_KIND = re.compile(r"^(VST3i|VST3|VSTi|VST|AUi|AU|CLAPi|CLAP|JS|LV2i|LV2|DX)\s*:\s*", re.I)
_STEM = re.compile(r"^(?P<plug>.*?) (?P<kind>VST3i|VST3I|VST3|VSTi|VST|AU|CLAP)(?P<rest>(?: by .*| \(\d+\))*)$")


def plugin_of(header: str) -> tuple[str, str]:
    """(plug-in name, maker) from a library's first line: 'VST3: Pianoteq 9 (Modartt)' gives
    ('Pianoteq 9', 'Modartt'); 'AU: Apple: AUDelay' gives ('AUDelay', 'Apple')."""
    from .inventory import split_display
    display = _KIND.sub("", header.strip(), count=1)
    if header.upper().startswith("AU") and ": " in display and not display.endswith(")"):
        maker, name = display.split(": ", 1)
        return name.strip(), maker.strip()
    return split_display(display)


def rename_payload(data: bytes, old: str, new: str) -> bytes:
    """A VST3 preset as REAPER saves it ends with its own name: 00, name, 00, 10 00 00 00.
    Renamed presets get the new name there too, as REAPER would write it. Any other layout is
    left exactly as it was."""
    tail = b"\x00" + old.encode("utf-8") + b"\x00\x10\x00\x00\x00"
    if old != new and data.endswith(tail):
        return data[:-len(tail)] + b"\x00" + new.encode("utf-8") + b"\x00\x10\x00\x00\x00"
    return data


def category_map(found: list, prefix: bool = True) -> dict:
    """{name as a library may hold it (lower case): category} for one plug-in's preset files.
    A name found in two categories can't say which it is, so it isn't in the map."""
    out: dict = {}
    clash = set()
    for f, cat, full in zip(found, categories(found), preset_names(found, True)):
        if not cat:
            continue
        for key in {states.clean_name(f.name).lower(), full.lower()}:
            if key in out and out[key] != cat:
                clash.add(key)
            out.setdefault(key, cat)
    for k in clash:
        out.pop(k, None)
    return out


def _lookup(cmap: dict, name: str) -> str:
    n = name.lower()
    if n in cmap:
        return cmap[n]
    m = re.match(r"^(.*) \(\d+\)$", n)     # "Glue (2)": a second preset with the same name
    return cmap.get(m.group(1), "") if m else ""


def organize_library(text: str, cmap: dict | None, prefix: bool = True) -> tuple[str, list, int]:
    """One library's text, organized. Returns (plug-in line, [(name, payload, category)],
    how many presets were renamed). Presets are in the library's order, or by name once any
    was renamed, so each category sits together."""
    plug, presets = states.parse_rpl(text)
    out, renamed = [], 0
    for name, data in presets:
        cat = _lookup(cmap, name) if cmap else ""
        new = prefixed(cat, name) if (prefix and cat) else name
        out.append([new, data, cat, name])
    finals = states.unique_names([o[0] for o in out])
    rows = []
    for (new, data, cat, old), final in zip(out, finals):
        if final != old:
            renamed += 1
        rows.append((final, rename_payload(data, old, final), cat))
    if renamed:
        rows.sort(key=lambda r: sort_key(r[0]))
    return plug, rows, renamed


def category_file_name(stem: str, category: str) -> str:
    """'Knifonium VST3i by Sam' and 'Bass' give 'Knifonium - Bass VST3i by Sam'."""
    m = _STEM.match(stem)
    if m:
        return f"{m.group('plug')}{SEP}{category} {m.group('kind')}{m.group('rest')}"
    return f"{stem}{SEP}{category}"


def organize_folder(src: str, dst: str, plugs: list | None = None, prefix: bool = True, per_category: bool = False,
                    layout: str = "plugin", min_keep: int = 5, log=None) -> dict:
    """Copy every library under `src` into `dst`, organized; `src` is never changed.

    Folders the libraries already sit in are kept (someone sorted them that way), with a folder
    per plug-in added below when `layout` is "plugin". A library at the top of `src` goes in
    its maker's folder. Other files (a read-me) are copied to the same place. When `plugs`
    (installed plug-ins with their preset files found) knows a library's plug-in, its presets
    get their maker's categories. Returns counts for the report and for speech."""
    from .inventory import norm
    log = log or (lambda s: None)
    src, dst = os.path.abspath(src), os.path.abspath(dst)
    if os.path.normcase(dst) == os.path.normcase(src) or os.path.normcase(dst).startswith(os.path.normcase(src) + os.sep):
        raise ValueError("the organized copy has to go outside the folder being organized")
    by_fx, by_name = {}, {}
    for p in plugs or []:
        if p.count:
            by_fx.setdefault(p.fx.lower(), p)
            by_name.setdefault((norm(p.name), norm(p.vendor)), p)
    stats = {"libraries": 0, "files": 0, "presets": 0, "renamed": 0, "categorized": [], "plain": [],
             "unreadable": [], "copied": 0, "lines": []}
    written = set()
    for dp, dn, fn in os.walk(src):
        dn.sort()
        for f in sorted(fn):
            path = os.path.join(dp, f)
            rel_dir = os.path.relpath(dp, src)
            rel_dir = "" if rel_dir == "." else rel_dir
            if f.startswith(".") or f.lower().endswith((".tmp",)):
                continue
            if not f.lower().endswith(".rpl"):
                target = os.path.join(dst, rel_dir, f)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(path, target)
                stats["copied"] += 1
                continue
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
                plug_line, _ = states.parse_rpl(text)
            except (OSError, ValueError) as e:
                stats["unreadable"].append((os.path.join(rel_dir, f), str(e)))
                continue
            name, vendor = plugin_of(plug_line)
            p = by_fx.get(plug_line.lower()) or by_name.get((norm(name), norm(vendor)))
            cmap = category_map(p.best()[1]) if p else None
            plug_line, rows, renamed = organize_library(text, cmap, prefix)
            base = os.path.join(dst, rel_dir) if rel_dir else library_dir(dst, vendor, name, "maker")
            folder = os.path.join(base, safe_name(name, FOLDER_LIMIT)) if layout == "plugin" else base
            stem = os.path.splitext(f)[0]
            cats = {r[2] for r in rows if r[2]}
            if per_category and len(cats) >= 2:
                parts: dict = {}
                for r in rows:
                    parts.setdefault(r[2].split(SEP)[0] if r[2] else OTHER, []).append(r)
                # categories smaller than a library worth keeping go together, as when making them
                small = [k for k, v in parts.items() if k != OTHER and len([r for r in v if r[0] != DEFAULT]) < min_keep]
                for k in small:
                    parts.setdefault(OTHER, []).extend(parts.pop(k))
                pieces = sorted(parts.items(), key=lambda x: (x[0] == OTHER, x[0].lower()))
                first = [r for _l, items in pieces for r in items if r[0] == DEFAULT]
                if first:   # 0 Default settings in the first file only, at its top
                    pieces = [(lab, [r for r in items if r[0] != DEFAULT]) for lab, items in pieces]
                    pieces[0] = (pieces[0][0], first + pieces[0][1])
                pieces = [(category_file_name(stem, label), items) for label, items in pieces]
            else:
                pieces = [(stem, rows)]
            os.makedirs(folder, exist_ok=True)
            for piece_stem, items in pieces:
                target = os.path.join(folder, safe_name(piece_stem) + os.path.splitext(f)[1])
                k = 2
                while target.lower() in written:
                    target = os.path.join(folder, safe_name(f"{piece_stem} ({k})") + os.path.splitext(f)[1])
                    k += 1
                written.add(target.lower())
                with open(target, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(states.rpl_text(plug_line, [(n, d) for n, d, _c in items]))
                stats["files"] += 1
                stats["lines"].append(f"{os.path.relpath(target, dst)}: {len(items)} presets")
            stats["libraries"] += 1
            stats["presets"] += len(rows)
            stats["renamed"] += renamed
            (stats["categorized"] if cats else stats["plain"]).append(name)
            log(f"{os.path.join(rel_dir, f)}: {len(rows)} presets, {renamed} renamed, "
                f"{len(cats)} {'category' if len(cats) == 1 else 'categories'}")
    return stats


def report_text(stats: dict, src: str, dst: str) -> str:
    L = [f"Organized the libraries in {src}", f"into {dst}", "",
         f"{stats['libraries']} libraries, {stats['presets']} presets, in {stats['files']} files.",
         f"{len(stats['categorized'])} {'library' if len(stats['categorized']) == 1 else 'libraries'} "
         f"had categories from {'its maker' if len(stats['categorized']) == 1 else 'their makers'}; "
         f"{stats['renamed']} preset names now start with their category.",
         f"{len(stats['plain'])} had no categories to add, so their names are as they were.",
         "The original folder wasn't changed.", ""]
    if stats["categorized"]:
        L.append("With categories: " + ", ".join(sorted(set(stats["categorized"]), key=str.lower)) + ".")
        L.append("")
    if stats["unreadable"]:
        for f, why in stats["unreadable"]:
            L.append(f"Not a library REAPER can import, left out: {f} ({why}).")
        L.append("")
    if stats["copied"]:
        L.append(f"{stats['copied']} other files (such as read-me files) were copied as they were.")
        L.append("")
    L.append("Files:")
    L += ["  " + x for x in stats["lines"]]
    return "\n".join(L) + "\n"


def organized_name(src: str) -> str:
    """'<folder> (organized)' beside it, numbered if that's already there."""
    src = os.path.abspath(src.rstrip("/\\"))
    out = src + " (organized)"
    k = 2
    while os.path.exists(out):
        out = f"{src} (organized {k})"
        k += 1
    return out


def save_report(text: str) -> str:
    """The organize report goes in this app's own folder, not among the libraries, so a
    folder made for sharing holds only what's meant to be shared."""
    import datetime
    from .inventory import SUPPORT
    d = os.path.join(SUPPORT, "reports")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"Organized {datetime.datetime.now():%Y-%m-%d %H.%M.%S}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path
