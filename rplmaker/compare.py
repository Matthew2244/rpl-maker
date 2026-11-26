"""Did the plug-in really take the preset? Compare what it saves back with what the file holds.

After REAPER applies a preset, the plug-in is asked for its state again. When that state is
byte for byte the file's, the preset is exact. Otherwise both are decoded, where the format is
known, into named values and compared value by value:

  iZotope     zlib-compressed JSON, the DSP values
  XLN         COTT key/value pairs
  Brainworx   "Pmtr" blocks of tagged floats (Plugin Alliance)
  JUCE XML    VC2! XML inside the VST3 wrapper, attribute by attribute
  ValueTree   JUCE binary PARAM entries (Bettermaker)
  ValueTree   any JUCE ValueTree in its binary form, property by property, with XML inside a
              property opened up (IK Multimedia's MODO, Pianoverse, SampleTank)
  XML         any state that is plain XML, as it stands or inside the VST2-style wrapper
              without JUCE's VC2! header (IK Multimedia)

A plug-in that re-saves in a newer format may add or drop keys; only the values both sides
hold count, and at least 95% of the file's current values must come back. A value snapping
to the plug-in's own control step (0.3512 -> 0.3495) is how the factory file itself loads,
so a difference of 0.02 or less on a value between -1.5 and 1.5 counts as a match.

When the state can't be read at all, the preset passes on the plug-in's controls instead:
they must move away from the defaults (unless the file *is* the default). Those are counted
separately so the report can say how each one was checked.
"""
from __future__ import annotations

import collections
import json
import re
import struct
import xml.etree.ElementTree as ET
import zlib

from . import states

UI_ONLY = {"isModulationVisible", "instanceSerial", "pluginVersion", "presetName", "uiWidth", "uiHeight",
           "minimize", "minimized", "BuildDate", "Version", "PresetName", "PresetSaveName",
           "PresetMidiOrigin", "editorWidth", "editorHeight", "lastPresetName", "currentPreset",
           "presetDirty", "windowWidth", "windowHeight", "zoom", "scale",
           # IK Multimedia: window size and panel layout
           "GuiScale", "GuiWidthRatio", "GuiHeightRatio", "UIState",
           # IK Multimedia: the name of the preset last chosen in the plug-in's own browser
           "_preset_name", "_preset_is_consisten", "_preset_is_consistent",
           # which build of the plug-in saved it (SampleTank 4)
           "BuildVersion"}
IGNORE_PARTS = ("/Active Band", "/Context State/", "Preset State/Extra Bytes", "/Analytics", "analytics",
                "/UIState/",
                # SampleTank 4's strummer: whether it was playing when saved, not a setting
                "/Strummer[1]/CurrentState[1]/Play")


# ---- decoders: state bytes -> {key: value} -----------------------------------------------

def _iz(comp):
    if comp[16:18] not in (b"\x78\x9c", b"\x78\xda", b"\x78\x01", b"\x78\x5e"):
        return None
    _m, _v, cs, us = struct.unpack("<4sIII", comp[:16])
    js = zlib.decompress(comp[16:16 + cs])
    out = {}

    def flat(j, p=""):
        if isinstance(j, dict) and "Type" in j and j["Type"] != "Dictionary":
            out[p] = (j["Type"], j.get("Value"))
            return
        if isinstance(j, dict):
            if j.get("Type") == "Dictionary":
                return flat(j["Value"], p)
            for k, v in j.items():
                flat(v, p + "/" + k)
    flat(json.loads(js))
    return {k: v for k, v in out.items() if k.startswith("/DSP State/")}


def _xln(comp):
    i = comp.find(b"COTT")
    if i < 0:
        return None
    parts = comp[i:].split(b"\x00")
    return dict(zip(parts[::2], parts[1::2]))


def _pmtr(comp):
    j = comp.find(b"Pmtr", 0, 64)
    if j < 0:
        return None
    c = comp[j:]
    _total, _x, n, per, _z = struct.unpack(">IIIII", c[4:24])
    d, p = {}, 24
    for _ in range(n):
        tag = c[p:p + 4].decode("latin-1")
        vals = struct.unpack(">" + "f" * per, c[p + 4:p + 4 + 4 * per])
        if tag != "Prst":   # which internal preset the plug-in's own menu shows
            d[tag] = vals[0]
        p += 4 + 4 * per
    return d


def _xml_values(text: bytes):
    root = ET.fromstring(text.rstrip(b"\x00").decode("utf-8", "replace"))
    out = {}

    def walk(e, path):
        seen = collections.Counter()
        if e.text and e.text.strip() and e.tag not in UI_ONLY:
            out[path + "#text"] = e.text.strip()
        for k, v in e.attrib.items():
            if k not in UI_ONLY:
                out[f"{path}@{k}"] = v
        for c in e:
            seen[c.tag] += 1
            walk(c, f"{path}/{c.tag}[{seen[c.tag]}]")
    walk(root, root.tag)
    return out


def _juce_xml(comp):
    chunk = comp
    if comp[:4] == b"VstW":
        chunk = states.juce_split(comp)[2]
    if chunk[:4] != b"VC2!":
        return None
    n = struct.unpack("<I", chunk[4:8])[0]
    return _xml_values(chunk[8:8 + n])


VT = re.compile(rb"PARAM\x00\x01\x03NAME\x00\x01.\x05([^\x00]*)\x00PARAM_ID\x00\x01.\x01(.{4})VALUE\x00\x01\x09\x04(.{8})", re.S)


def _valuetree(comp):
    if comp[:4] == b"VstW":
        comp = states.juce_split(comp)[2]
    d = {}
    for nm, pid, val in VT.findall(comp):
        d[nm.decode("latin-1") + "#" + pid.hex()] = struct.unpack("<d", val)[0]
    return d or None


def _cint(b: bytes, i: int):
    """JUCE's OutputStream::writeCompressedInt: a byte giving how many bytes follow (0x80 set
    for a negative number), then those bytes, low first."""
    n = b[i]
    k = n & 0x7f
    if k > 4:
        raise ValueError("bad compressed int")
    v = int.from_bytes(b[i + 1:i + 1 + k], "little")
    return (-v if n & 0x80 else v), i + 1 + k


def _cstr(b: bytes, i: int):
    j = b.index(b"\x00", i)
    return b[i:j].decode("utf-8", "replace"), j + 1


def _jvar(b: bytes, i: int):
    """One juce::var as var::writeToStream writes it: size (type byte included), type, data."""
    size, i = _cint(b, i)
    if size == 0:
        return None, i
    t, data, end = b[i], b[i + 1:i + size], i + size
    if end > len(b):
        raise ValueError("var runs past the end")
    if t == 1:
        return struct.unpack("<i", data[:4])[0], end
    if t in (2, 3):
        return t == 2, end
    if t == 4:
        return struct.unpack("<d", data[:8])[0], end
    if t == 5:
        return data.rstrip(b"\x00").decode("utf-8", "replace"), end
    if t == 6:
        return struct.unpack("<q", data[:8])[0], end
    if t == 7:
        n, j = _cint(b, i + 1)
        items = []
        for _ in range(n):
            v, j = _jvar(b, j)
            items.append(v)
        return items, end
    if t == 8:
        return bytes(data), end
    if t == 9:
        return None, end
    raise ValueError(f"var type {t}")


_TREE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_ .:-]{0,127}$")   # a ValueTree type or property name


def _tree(b: bytes, i: int, path: str, out: dict, depth: int = 0):
    """ValueTree::writeToStream: type name, properties, children."""
    if depth > 64:
        raise ValueError("too deep")
    name, i = _cstr(b, i)
    if not _TREE_NAME.match(name):
        raise ValueError("not a ValueTree")
    here = f"{path}/{name}" if path else name
    n, i = _cint(b, i)
    if n < 0 or n > 100000:
        raise ValueError("not a ValueTree")
    for _ in range(n):
        key, i = _cstr(b, i)
        if not _TREE_NAME.match(key):
            raise ValueError("not a ValueTree")
        v, i = _jvar(b, i)
        if key in UI_ONLY:
            continue
        _flat_value(f"{here}@{key}", v, out)
    kids, i = _cint(b, i)
    if kids < 0 or kids > 100000:
        raise ValueError("not a ValueTree")
    seen = collections.Counter()
    for _ in range(kids):
        j = b.index(b"\x00", i)
        tag = b[i:j].decode("utf-8", "replace")
        seen[tag] += 1
        i = _tree(b, i, f"{here}[{seen[tag]}]" if seen[tag] > 1 else here, out, depth + 1)
    return i


JUCE_B64 = ".ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+"
_JB64 = re.compile(r"^(\d{1,9})\.([.A-Za-z0-9+]*)$")


def juce_base64(text: str) -> bytes | None:
    """JUCE's MemoryBlock::toBase64Encoding ("<size>." then six bits a character, low bit
    first, in its own alphabet), as plug-ins store a block of binary inside a property."""
    m = _JB64.match(text.strip())
    if not m:
        return None
    size = int(m.group(1))
    if size > 64 * 1024 * 1024 or len(m.group(2)) * 6 < size * 8:
        return None
    out = bytearray(size)
    pos = 0
    for ch in m.group(2):
        v = JUCE_B64.index(ch)
        for i in range(6):
            if pos >= size * 8:
                break
            if v >> i & 1:
                out[pos >> 3] |= 1 << (pos & 7)
            pos += 1
    return bytes(out)


def _flat_value(key: str, v, out: dict):
    """A property's value; XML held inside one (as text, or JUCE's VC2! binary) is opened up so
    its settings are compared one by one, anything else is compared whole."""
    if isinstance(v, bytes) and v[:4] == b"VC2!":
        n = struct.unpack("<I", v[4:8])[0]
        try:
            for k2, v2 in _xml_values(v[8:8 + n]).items():
                out[f"{key}/{k2}"] = v2
            return
        except ET.ParseError:
            pass
    if isinstance(v, str) and v.lstrip().startswith("<"):
        try:
            for k2, v2 in _xml_values(v.encode("utf-8")).items():
                out[f"{key}/{k2}"] = v2
            return
        except ET.ParseError:
            pass
    if isinstance(v, str) and _JB64.match(v):
        blob = juce_base64(v)
        if blob is not None:   # a block inside a property: open it up when it's a tree or XML too
            inner: dict = {}
            try:
                end = _tree(blob, 0, "", inner)
                if inner and end >= 16:   # names are checked, so a short tree is still a tree
                    for k2, v2 in inner.items():
                        out[f"{key}/{k2}"] = v2
                    # what follows the tree is left alone: IK's blocks carry whatever was in
                    # memory after it, different every save (MODO BASS 2)
                    return
            except (ValueError, IndexError, struct.error):
                pass
            _flat_value(key, blob, out)
            return
    if isinstance(v, list):
        for n, x in enumerate(v):
            _flat_value(f"{key}[{n}]", x, out)
        return
    out[key] = v


def _juce_tree(comp):
    """A juce::ValueTree in its binary form (writeToStream), as it stands or as the chunk inside
    the VST2-style VST3 wrapper: IK Multimedia's MODO BASS 2, MODO DRUM, Pianoverse and
    SampleTank 4. Every property by path; XML inside a property is opened up too."""
    chunk = states.juce_split(comp)[2] if comp[:4] == b"VstW" else comp
    if not chunk or chunk[:1] in (b"<", b"\x00") or chunk[:4] == b"VC2!":
        return None
    out: dict = {}
    end = _tree(chunk, 0, "", out)
    tail = chunk[end:]
    # JUCE's VST3 wrapper adds its own block (bypass state) after the plug-in's data
    if len(tail.rstrip(b"\x00")) > 16 and b"JUCEPrivateData" not in tail:
        return None   # mostly unread: not a ValueTree after all
    return out or None


def _plain_xml(comp):
    s = comp.lstrip(b"\xef\xbb\xbf").lstrip()
    if not s.startswith(b"<"):
        return None
    end = s.rfind(b">")
    return _xml_values(s[:end + 1])


def _wrapped_xml(comp):
    """Plain XML as the chunk inside the VST2-style VST3 wrapper (VstW, then a CcnK/FBCh bank),
    without JUCE's VC2! header: IK Multimedia (Hammond B-3X, MODO BASS 2, MODO DRUM)."""
    if comp[:4] != b"VstW":
        return None
    return _plain_xml(states.juce_split(comp)[2])


DECODERS = [("iZotope", _iz), ("Brainworx", _pmtr), ("JUCE XML", _juce_xml), ("ValueTree", _valuetree),
            ("XLN", _xln), ("XML", _plain_xml), ("wrapped XML", _wrapped_xml), ("JUCE ValueTree", _juce_tree)]


def decode(comp: bytes):
    """(decoder name, {key: value}) or (None, None) when the state is opaque."""
    for name, fn in DECODERS:
        try:
            d = fn(comp)
        except Exception:  # noqa: BLE001
            d = None
        if d:
            d = {k: v for k, v in d.items() if not any(x in str(k) for x in IGNORE_PARTS)}
            if d:
                return name, d
    return None, None


# ---- comparing -----------------------------------------------------------------------------

def _num(v):
    if isinstance(v, tuple):
        v = v[1]
    if isinstance(v, bytes):
        v = v.decode("latin-1")
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def same(a, b) -> str | None:
    """'same', 'rounded' (a control-step snap) or None when the values differ."""
    if a == b:
        return "same"
    # a file path saved on Windows reads back with the Mac's separators (SampleTank 4's NKS
    # files were made on Windows: "Instruments\\50__Miroslav..." comes back "Instruments/50__...")
    if isinstance(a, str) and isinstance(b, str) and ("\\" in a or "\\" in b) \
            and a.replace("\\", "/") == b.replace("\\", "/"):
        return "same"
    x, y = _num(a), _num(b)
    if x is None or y is None:
        return None
    if abs(x - y) <= 1e-5 * max(1.0, abs(x)):
        return "same"
    if abs(x) <= 1.5 and abs(y) <= 1.5 and abs(x - y) <= 0.02:
        return "rounded"
    return None


def pretty_key(key) -> str:
    """'root/modulation[1]/mods[1]/mod_0[1]/buttons[1]/button[1]@name' -> 'button name';
    '/DSP State/Band 1/Gain' -> 'Band 1 Gain'. Enough to recognise, short enough to hear."""
    k = key.decode("latin-1") if isinstance(key, bytes) else str(key)
    k = re.sub(r"\[1\]", "", k).replace("@", "/").replace("#text", "").replace("#", " ")
    parts = [p for p in k.split("/") if p and p != "DSP State"]
    return " ".join(parts[-2:]) if parts else k


def short(v) -> str:
    if isinstance(v, tuple):
        v = v[1]
    if v is None or v == "" or v == b"":
        return "nothing"
    if isinstance(v, bytes):   # read aloud, a block of binary is noise: say how big it is
        return f"a block of {len(v):,} bytes" if not v.isascii() or b"\x00" in v else short(v.decode("ascii"))
    if isinstance(v, str) and len(v) > 24 and (_JB64.match(v) or not any(c == " " for c in v)):
        return f"a block of {len(v):,} characters"
    x = _num(v)
    if x is not None and not isinstance(v, bool):
        return f"{x:.4g}"
    return str(v)[:24]


class Verdict:
    """One preset's result. how: 'exact', 'values', 'rounded', 'controls'; or ok False and why."""

    def __init__(self, ok: bool, how: str = "", why: str = ""):
        self.ok, self.how, self.why = ok, how, why

    def __repr__(self):
        return f"Verdict({self.ok}, {self.how!r}, {self.why!r})"


def judge(name: str, k: int, src: bytes, line: str | None, default_state: dict, default_pv: str) -> Verdict:
    """src: the payload written for preset k. line: the worker's P line for it (or None)."""
    if line is None:
        return Verdict(False, why="REAPER never got to it")
    _p, _k, okset, cur, pname, pv, blk = line.split("\t", 6)
    if pname != name or okset != "true" or cur != str(k):
        return Verdict(False, why="REAPER didn't select it by name" + (f" (it said {pname!r})" if pname != name else ""))
    try:
        got = states.parse_state(states.chunk_state(blk.split("|")))["comp"]
    except Exception:  # noqa: BLE001
        return Verdict(False, why="the plug-in's saved state couldn't be read back")
    want = states.parse_state(src)["comp"]
    if got == want:
        return Verdict(True, "exact")
    da, A = decode(want)
    db, B = decode(got)
    if A and B and da == db:
        _dd, D = decode(default_state["comp"])
        live = set(D) if D and _dd == da else None
        need = (set(A) & live) if live else set(A)
        if not need:
            need = set(A)
        both = need & set(B)
        if len(both) < 0.95 * len(need):
            return Verdict(False, why=f"only {len(both)} of its {len(need)} settings came back")
        rounded = False
        bad = []
        for key in both:
            r = same(A[key], B[key])
            if r is None:
                bad.append(key)
            elif r == "rounded":
                rounded = True
        if bad:
            key = sorted(bad, key=str)[0]
            return Verdict(False, why=f"{len(bad)} of its {len(both)} settings changed when loaded, "
                                      f"for example {pretty_key(key)}: {short(A[key])} became {short(B[key])}")
        return Verdict(True, "rounded" if rounded else "values")
    # opaque: judge by the plug-in's controls
    if want == default_state["comp"]:
        return Verdict(True, "controls")
    if pv == default_pv:
        return Verdict(False, why="the plug-in stayed at its default settings")
    return Verdict(True, "controls")


HOW_WORDS = {"exact": "saved back exactly as written",
             "values": "every setting matched",
             "rounded": "every setting matched, some rounded to the control's own steps",
             "controls": "checked by its controls (the plug-in's own format can't be read)"}
