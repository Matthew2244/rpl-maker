"""REAPER's VST3 FX state, and the .RPL and preset .ini files that carry it.

A REAPER VST3 preset payload, as REAPER itself saves it (and as shared RPL libraries hold it):

    prefix                      plug-in magic + pin layout, exactly as REAPER captured it
    u32 total (=16+comp+ctrl), u32 1, marker (ff ff 10 00 for nearly every plug-in)
    u32 len(comp), u32 1, comp      the VST3 component state (what a .vstpreset calls Comp)
    u32 len(ctrl), u32 0, ctrl      the controller state (Cont)
    00, preset name, 00, 10 00 00 00

Nothing here guesses at a plug-in's own format: comp and ctrl are byte copies of what the
plug-in or its preset file wrote.
"""
from __future__ import annotations

import base64
import re
import struct


def parse_state(b: bytes) -> dict:
    """Split a REAPER VST3 state into prefix/comp/ctrl/tail. The marker is found by checking
    the sizes around it add up, because some pin-layout prefixes contain ff ff themselves and
    a few plug-ins use 00 00 00 00 as the marker."""
    for m in range(8, len(b) - 12):
        try:
            tot, one = struct.unpack("<II", b[m - 8:m])
            if one != 1:
                continue
            cl = struct.unpack("<I", b[m + 4:m + 8])[0]
            if cl > len(b):
                continue
            tl = struct.unpack("<I", b[m + 12 + cl:m + 16 + cl])[0]
        except struct.error:
            continue
        if tot == 16 + cl + tl and m + 16 + cl + tl <= len(b):
            comp = b[m + 12:m + 12 + cl]
            p = m + 12 + cl
            ctrl = b[p + 8:p + 8 + tl]
            return dict(prefix=b[:m - 8], marker=b[m:m + 4], comp=comp, ctrl=ctrl, tail=b[p + 8 + tl:])
    raise ValueError("this doesn't look like a VST3 state REAPER saved")


def payload(st: dict, comp: bytes, name: str, ctrl: bytes = b"") -> bytes:
    """A preset payload for the plug-in whose default state is `st`."""
    nm = name.encode("utf-8")
    return (st["prefix"] + struct.pack("<II", 16 + len(comp) + len(ctrl), 1) + st["marker"][:2] + b"\x10\x00"
            + struct.pack("<II", len(comp), 1) + comp
            + struct.pack("<II", len(ctrl), 0) + ctrl
            + b"\x00" + nm + b"\x00" + b"\x10\x00\x00\x00")


def chunk_state(lines: list[str]) -> bytes:
    """The bytes inside a <VST ...> block of a track chunk (its base64 lines)."""
    return b"".join(base64.b64decode(x.strip()) for x in lines if x.strip())


def quote(name: str) -> str:
    for q in ("`", '"', "'"):
        if q not in name:
            return q + name + q
    raise ValueError("name has every quote character: " + name)


def clean_name(name: str) -> str:
    """A preset name REAPER can hold: one line, no NUL, no leading/trailing space, and not
    using all three quote characters."""
    name = re.sub(r"[\x00-\x1f]+", " ", name).strip()
    if all(q in name for q in "`\"'"):
        name = name.replace("`", "'")
    return name or "Untitled"


def rpl_text(plugname: str, presets: list[tuple[str, bytes]]) -> str:
    plugname = plugname.replace('"', "'")
    out = ['<REAPER_PRESET_LIBRARY "' + plugname + '"']
    for name, data in presets:
        out.append("  <PRESET " + quote(name))
        b = base64.b64encode(data).decode()
        for k in range(0, len(b), 128):
            out.append("    " + b[k:k + 128])
        out.append("  >")
    out.append(">")
    return "\n".join(out) + "\n"


def parse_rpl(text: str) -> tuple[str, list[tuple[str, bytes]]]:
    m = re.search(r'^<REAPER_PRESET_LIBRARY\s+(?:"([^"]+)"|`([^`]+)`)', text, re.M)
    if not m:
        raise ValueError("not a REAPER preset library")
    plug = m.group(1) or m.group(2)
    presets = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("<PRESET"):
            rest = s[len("<PRESET"):].strip()
            if rest[:1] in "`\"'":
                q = rest[0]
                name = rest[1:rest.index(q, 1)]
            else:
                name = rest.split()[0] if rest else ""
            b64 = []
            i += 1
            while i < len(lines) and lines[i].strip() != ">":
                b64.append(lines[i].strip())
                i += 1
            presets.append((name, base64.b64decode("".join(b64))))
        i += 1
    return plug, presets


def ini_text(presets: list[tuple[str, bytes]]) -> str:
    """REAPER's presets/*.ini layout: each payload in 16384-byte pieces of uppercase hex, each
    piece followed by a checksum byte (sum of its bytes mod 256)."""
    out = ["[General]", f"NbPresets={len(presets)}", ""]
    for n, (name, data) in enumerate(presets):
        out.append(f"[Preset{n}]")
        for c, off in enumerate(range(0, len(data), 16384)):
            piece = data[off:off + 16384]
            out.append(("Data" if c == 0 else f"Data_{c}") + "=" + piece.hex().upper() + format(sum(piece) & 255, "02X"))
        out.append(f"Len={len(data)}")
        out.append(f"Name={name}")
        out.append("")
    return "\n".join(out)


def unique_names(names: list[str]) -> list[str]:
    seen, out = set(), []
    for n in names:
        base, k = n, 2
        while n.lower() in seen:
            n = f"{base} ({k})"
            k += 1
        seen.add(n.lower())
        out.append(n)
    return out


# ---- JUCE: the way JUCE's VST3 wrapper stores state ----------------------------------------
# VstW header, then an fxb-style bank (CcnK ... FBCh ... chunk), then JUCE's private data.

def juce_split(comp: bytes):
    if comp[:4] != b"VstW":
        raise ValueError("not a JUCE VST3 state")
    hl = struct.unpack(">I", comp[4:8])[0]
    hdr = comp[:8 + hl]
    p = 8 + hl
    if comp[p:p + 4] != b"CcnK":
        raise ValueError("no CcnK bank")
    bsize = struct.unpack(">I", comp[p + 4:p + 8])[0]
    bank = comp[p:p + 8 + bsize]
    rest = comp[p + 8 + bsize:]
    if bank[8:12] != b"FBCh":
        raise ValueError("not a chunk bank")
    head = bank[:8 + 4 * 5 + 128]
    csz = struct.unpack(">I", bank[len(head):len(head) + 4])[0]
    chunk = bank[len(head) + 4:len(head) + 4 + csz]
    return hdr, head, chunk, rest


def juce_wrap(default_comp: bytes, chunk: bytes) -> bytes:
    """Put a plug-in's own state blob (getStateInformation) where JUCE's VST3 wrapper keeps it,
    using the plug-in's default state as the template."""
    hdr, head, _old, rest = juce_split(default_comp)
    body = head[8:] + struct.pack(">I", len(chunk)) + chunk
    return hdr + b"CcnK" + struct.pack(">I", len(body)) + body + rest


def vc2(xml: bytes) -> bytes:
    """JUCE's binary wrapper for an XML state (copyXmlToBinary)."""
    x = xml + b"\x00"
    return b"VC2!" + struct.pack("<I", len(x)) + x


def is_juce(comp: bytes) -> bool:
    try:
        juce_split(comp)
        return True
    except Exception:  # noqa: BLE001
        return False
