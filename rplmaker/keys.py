"""Every menu shortcut, in one place, without wx, so a test can check that each key means one
thing on every system.

wx reads "Ctrl" as Command on a Mac and Control on Windows, so one string serves both and the
two systems get the same keys. Two come from REAPER, so they're where its users' hands already
are: Preferences is Command+P / Control+P, REAPER's own; Say Progress is OSARA's "Report
track/item/time/MIDI selection", Command+Shift+Space on a Mac and Control+Shift+Space on
Windows (KEY 13 32 _OSARA_REPORTSEL in OSARA's config/mac and config/windows reaper-kb.ini;
REAPER's Mac keymap reads its Control flag as Command). Command+Shift+Space is no macOS
shortcut: Control+Space and Control+Option+Space switch input sources, Command+Space is
Spotlight, Command+Option+Space a Finder search.
"""
from __future__ import annotations

import sys

MAC = sys.platform == "darwin"

SHORTCUTS = {
    "make": "Ctrl+B",
    "stop": "Ctrl+.",
    "scan": "Ctrl+R",
    "folder": "Ctrl+Shift+F",
    "report": "Ctrl+Shift+R",
    "preferences": "Ctrl+P",
    "quit": "Ctrl+Q",
    "check_all": "Ctrl+Shift+A",
    "uncheck_all": "Ctrl+Shift+U",
    "find": "Ctrl+F",
    "list": "Ctrl+L",
    "say_progress": "Ctrl+Shift+Space",
    "updates": "Ctrl+U",
}

# Keys that also do something, without showing in a menu. Command+Comma is where every Mac
# app keeps its preferences, and Magpie's Control+Comma opened them on Windows before 0.1.6,
# so it still does, on both.
ALSO = {
    "preferences": ["Ctrl+,"],
}

_NAMES = {".": "Period", ",": "Comma"}


def words(accel: str, mac: bool = MAC) -> str:
    """How a shortcut is said: "Command-Shift-Space" on a Mac, "Control+Shift+Space" on
    Windows, each system's own way of writing it."""
    parts = [{"Ctrl": "Command" if mac else "Control", "Alt": "Option" if mac else "Alt"}.get(p, p)
             for p in accel.split("+")]
    if accel.endswith("++"):
        parts = parts[:-2] + ["Plus"]
    parts = [_NAMES.get(p, p) for p in parts]
    return ("-" if mac else "+").join(parts)


def say(name: str, mac: bool = MAC) -> str:
    return words(SHORTCUTS[name], mac)


def every_key() -> list[str]:
    """Every key any menu item answers to, shown or not."""
    out = list(SHORTCUTS.values())
    for extra in ALSO.values():
        out += extra
    return out
