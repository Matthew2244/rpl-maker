"""Did the plug-in really take the preset? Compare what it saves back with what the file holds.

After REAPER applies a preset, the plug-in is asked for its state again. When that state is
byte for byte the file's, the preset is exact. Otherwise both are decoded, where the format is
known, into named values and compared value by value:

  iZotope     zlib-compressed JSON, the DSP values
  XLN         COTT key/value pairs
  Brainworx   "Pmtr" blocks of tagged floats (Plugin Alliance)
  JUCE XML    VC2! XML inside the VST3 wrapper, attribute by attribute
  ValueTree   JUCE binary PARAM entries (Bettermaker)
  XML         any state that is plain XML

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
           "presetDirty", "windowWidth", "windowHeight", "zoom", "scale"}
IGNORE_PARTS = ("/Active Band", "/Context State/", "Preset State/Extra Bytes", "/Analytics", "analytics")


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


def _plain_xml(comp):
    s = comp.lstrip(b"\xef\xbb\xbf").lstrip()
    if not s.startswith(b"<"):
        return None
    end = s.rfind(b">")
    return _xml_values(s[:end + 1])


DECODERS = [("iZotope", _iz), ("Brainworx", _pmtr), ("JUCE XML", _juce_xml), ("ValueTree", _valuetree),
            ("XLN", _xln), ("XML", _plain_xml)]


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
    if isinstance(v, bytes):
        v = v.decode("latin-1")
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
