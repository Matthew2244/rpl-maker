"""Read the preset files vendors install, without translating anything.

Every reader returns `Found` records: which plug-in a file belongs to (an exact VST3 class id,
or a VST2 four-character id, or a folder name) and how to make the plug-in's state from it.
Making the state is put off until the plug-in's default state is known (`make_state`),
because some formats need the plug-in's own wrapper around them.

A file this module can read is only a candidate. Whether the plug-in really accepts it is
decided in REAPER, preset by preset.
"""
from __future__ import annotations

import os
import plistlib
import struct
from dataclasses import dataclass, field

from . import states

# Formats, best first: when a plug-in has presets in several, the first one found is used.
FORMATS = ["vstpreset", "nks", "fxp", "aupreset", "xml"]
SHORT_WORDS = {"vstpreset": "VST3", "nks": "NKS", "fxp": "VST2", "aupreset": "Audio Unit", "xml": "XML"}
FORMAT_WORDS = {
    "vstpreset": "VST3 preset files",
    "nks": "Native Instruments NKS presets",
    "fxp": "VST2 preset files",
    "aupreset": "Audio Unit presets",
    "xml": "XML preset files",
}
PRESET_EXTS = {".vstpreset": "vstpreset", ".nksf": "nks", ".nksfx": "nks", ".fxp": "fxp",
               ".aupreset": "aupreset", ".xml": "xml",
               # XML presets under their makers' own names (Unfiltered Audio, LTL, Vertigo)
               ".uap": "xml", ".sbp": "xml", ".csp": "xml", ".vss2preset": "xml"}


@dataclass
class Found:
    path: str
    fmt: str
    name: str                      # the preset's own name (NKS carries it; else the file name)
    class_id: str | None = None    # 32 hex digits, upper case
    vst2: str | None = None        # four-character VST2 id, as 8 hex digits
    folder_hint: list[str] = field(default_factory=list)   # folder names, for XML matching
    plugin_name: str | None = None  # what the file says the plug-in is called, if it says


# ---- small binary helpers ---------------------------------------------------------------------

def riff(b: bytes) -> dict:
    if b[:4] != b"RIFF":
        raise ValueError("not RIFF")
    i, out = 12, {}
    while i + 8 <= len(b):
        cid = b[i:i + 4]
        n = struct.unpack("<I", b[i + 4:i + 8])[0]
        out[cid] = b[i + 8:i + 8 + n]
        i += 8 + n + (n & 1)
    return out


def vstpreset_parts(vp: bytes) -> tuple[str, dict]:
    """A .vstpreset image -> (class id, {chunk id: bytes})."""
    if vp[:4] != b"VST3":
        raise ValueError("not a .vstpreset")
    cls = vp[8:40].decode("ascii")
    lst = struct.unpack("<Q", vp[40:48])[0]
    if vp[lst:lst + 4] != b"List":
        raise ValueError("no chunk list")
    cnt = struct.unpack("<I", vp[lst + 4:lst + 8])[0]
    p, ch = lst + 8, {}
    for _ in range(cnt):
        cid = vp[p:p + 4]
        off, size = struct.unpack("<QQ", vp[p + 4:p + 20])
        p += 20
        ch[cid] = vp[off:off + size]
    return cls.upper(), ch


def msgpack(b: bytes, i: int = 0):
    """Decode one msgpack value at b[i]; returns (value, next index). Enough for NKS metadata."""
    t = b[i]
    if t <= 0x7f:
        return t, i + 1
    if 0x80 <= t <= 0x8f:
        return _map(b, i + 1, t & 0x0f)
    if 0x90 <= t <= 0x9f:
        return _arr(b, i + 1, t & 0x0f)
    if 0xa0 <= t <= 0xbf:
        n = t & 0x1f
        return b[i + 1:i + 1 + n].decode("utf-8", "replace"), i + 1 + n
    if t >= 0xe0:
        return t - 256, i + 1
    simple = {0xc0: None, 0xc2: False, 0xc3: True}
    if t in simple:
        return simple[t], i + 1
    sizes = {0xcc: ">B", 0xcd: ">H", 0xce: ">I", 0xcf: ">Q", 0xd0: ">b", 0xd1: ">h", 0xd2: ">i", 0xd3: ">q",
             0xca: ">f", 0xcb: ">d"}
    if t in sizes:
        f = sizes[t]
        n = struct.calcsize(f)
        return struct.unpack(f, b[i + 1:i + 1 + n])[0], i + 1 + n
    if t in (0xd9, 0xda, 0xdb, 0xc4, 0xc5, 0xc6):
        f = {0xd9: ">B", 0xda: ">H", 0xdb: ">I", 0xc4: ">B", 0xc5: ">H", 0xc6: ">I"}[t]
        k = struct.calcsize(f)
        n = struct.unpack(f, b[i + 1:i + 1 + k])[0]
        raw = b[i + 1 + k:i + 1 + k + n]
        return (raw.decode("utf-8", "replace") if t in (0xd9, 0xda, 0xdb) else raw), i + 1 + k + n
    if t in (0xdc, 0xdd):
        f = ">H" if t == 0xdc else ">I"
        k = struct.calcsize(f)
        return _arr(b, i + 1 + k, struct.unpack(f, b[i + 1:i + 1 + k])[0])
    if t in (0xde, 0xdf):
        f = ">H" if t == 0xde else ">I"
        k = struct.calcsize(f)
        return _map(b, i + 1 + k, struct.unpack(f, b[i + 1:i + 1 + k])[0])
    raise ValueError(f"msgpack type {t:#x}")


def _map(b, i, n):
    d = {}
    for _ in range(n):
        k, i = msgpack(b, i)
        v, i = msgpack(b, i)
        d[k] = v
    return d, i


def _arr(b, i, n):
    a = []
    for _ in range(n):
        v, i = msgpack(b, i)
        a.append(v)
    return a, i


def nks_meta(chunk: bytes) -> dict:
    """NISI / PLID chunks: a version word, then msgpack."""
    try:
        return msgpack(chunk, 4)[0] or {}
    except Exception:  # noqa: BLE001
        return {}


def fourcc_hex(v) -> str | None:
    if isinstance(v, int) and v:
        return f"{v & 0xffffffff:08X}"
    if isinstance(v, (bytes, str)) and len(v) == 4:
        return (v.encode("latin-1") if isinstance(v, str) else v).hex().upper()
    return None


# ---- readers -------------------------------------------------------------------------------

def read(path: str) -> Found | None:
    """Look at one file; None when it isn't something this can use."""
    ext = os.path.splitext(path)[1].lower()
    fmt = PRESET_EXTS.get(ext)
    stem = os.path.splitext(os.path.basename(path))[0]
    try:
        if fmt == "vstpreset":
            with open(path, "rb") as f:
                head = f.read(48)
            if head[:4] != b"VST3":
                return None
            return Found(path, fmt, stem, class_id=head[8:40].decode("ascii").upper())
        if fmt == "nks":
            with open(path, "rb") as f:
                c = riff(f.read(65536))   # the metadata comes first; the state can be huge
            pc = c.get(b"PCHK", b"")
            plid = nks_meta(c.get(b"PLID", b""))
            name = nks_meta(c.get(b"NISI", b"")).get("name") or stem
            fd = Found(path, fmt, str(name), plugin_name=plid.get("pluginName"))
            uid = plid.get("VST3.uid")
            if pc[4:8] == b"VST3":
                fd.class_id = pc[12:44].decode("ascii").upper()
            elif isinstance(uid, list) and len(uid) == 4 and any(uid):
                fd.class_id = "".join(f"{x & 0xffffffff:08X}" for x in uid)   # VST3 uid, state not a vstpreset
                fd.vst2 = fourcc_hex(plid.get("VST.magic"))
            else:
                fd.vst2 = fourcc_hex(plid.get("VST.magic"))
            if not (fd.class_id or fd.vst2):
                return None
            return fd
        if fmt == "fxp":
            with open(path, "rb") as f:
                h = f.read(60)
            if h[:4] != b"CcnK" or h[8:12] != b"FPCh":   # FxCk (a list of knob values) can't be a VST3 state
                return None
            name = h[28:56].split(b"\x00")[0].decode("latin-1").strip()
            return Found(path, fmt, stem or name, vst2=h[16:20].hex().upper())
        if fmt == "aupreset":
            with open(path, "rb") as f:
                pl = plistlib.load(f)
            if not any(k in pl for k in ("jucePluginState", "vstdata")):
                return None
            name = pl.get("name") or stem
            return Found(path, fmt, str(name), vst2=fourcc_hex(pl.get("subtype")))
        if fmt == "xml":
            with open(path, "rb") as f:
                head = f.read(512).lstrip(b"\xef\xbb\xbf").lstrip()
            if not head.startswith(b"<"):
                return None
            parts = os.path.dirname(path).split(os.sep)
            return Found(path, fmt, stem, folder_hint=parts[-4:])
    except Exception:  # noqa: BLE001 - an unreadable file is just not a candidate
        return None
    return None


def exact_copies(fmt: str, found: list) -> bool:
    """Do these files hold the VST3 state itself (so they usually all work), rather than a form
    that has to be fitted into it?"""
    return fmt == "vstpreset" or (fmt == "nks" and all(f.class_id and not f.vst2 for f in found[:20]))


def make_state(fd: Found, default: dict) -> tuple[bytes, bytes]:
    """(component state, controller state) for this preset, given the plug-in's default state
    as REAPER captured it. Raises ValueError when this format can't fit this plug-in."""
    dcomp, dctrl = default["comp"], default["ctrl"]
    with open(fd.path, "rb") as f:
        raw = f.read()
    if fd.fmt == "vstpreset":
        _cls, ch = vstpreset_parts(raw)
        if b"Comp" not in ch:
            raise ValueError("no component state in the file")
        return ch[b"Comp"], ch.get(b"Cont", b"")
    if fd.fmt == "nks":
        pc = riff(raw)[b"PCHK"]
        if pc[4:8] == b"VST3":
            _cls, ch = vstpreset_parts(pc[4:])
            return ch[b"Comp"], ch.get(b"Cont", b"")
        return _chunk(pc[4:], dcomp, dctrl)
    if fd.fmt == "fxp":
        size = struct.unpack(">I", raw[56:60])[0]
        return _chunk(raw[60:60 + size], dcomp, dctrl)
    if fd.fmt == "aupreset":
        pl = plistlib.loads(raw)
        blob = pl.get("jucePluginState") or pl.get("vstdata")
        return _chunk(bytes(blob), dcomp, dctrl)
    if fd.fmt == "xml":
        xml = raw.lstrip(b"\xef\xbb\xbf").replace(b"\r\n", b"\n").strip()
        if dcomp[:4] == b"VC2!":
            return states.vc2(xml), dctrl
        if states.is_juce(dcomp):
            inner = states.juce_split(dcomp)[2]
            if inner[:4] == b"VC2!":
                return states.juce_wrap(dcomp, states.vc2(xml)), dctrl
        raise ValueError("this plug-in doesn't keep its settings as XML")
    raise ValueError("unknown format")


def _chunk(chunk: bytes, dcomp: bytes, dctrl: bytes) -> tuple[bytes, bytes]:
    """A VST2-style opaque chunk. JUCE plug-ins keep the same blob inside their VST3 wrapper;
    others (Brainworx, many more) use it as the VST3 state as it stands."""
    if states.is_juce(dcomp):
        return states.juce_wrap(dcomp, chunk), dctrl
    return chunk, b""
