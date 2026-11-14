"""Settings, one JSON file. Unknown keys are kept, so an older copy never drops a newer one's."""
from __future__ import annotations

import json
import os
import sys

from .inventory import SUPPORT

PATH = os.path.join(SUPPORT, "settings.json")


def full_name() -> str:
    """The person's full name as the computer knows it, for file names; empty if unknown."""
    try:
        if sys.platform == "win32":
            import ctypes
            size = ctypes.c_ulong(0)
            ctypes.windll.secur32.GetUserNameExW(3, None, ctypes.byref(size))   # 3: NameDisplay
            buf = ctypes.create_unicode_buffer(size.value or 256)
            if ctypes.windll.secur32.GetUserNameExW(3, buf, ctypes.byref(size)):
                return buf.value.strip()
            return ""
        import pwd
        return (pwd.getpwuid(os.getuid()).pw_gecos or "").split(",")[0].strip()
    except Exception:  # noqa: BLE001
        return ""


DEFAULTS = {
    "out_dir": os.path.join(os.path.expanduser("~"), "Documents", "REAPER Preset Libraries"),
    "author": full_name(),       # file names read "<plug-in> VST3 by <name>.RPL"
    "min_keep": 5,
    "check_twice": True,
    "split_big": True,           # one library per folder for a big set (an ADpak, an instrument)
    "split_over": 300,
    "extra_folders": [],
    "speak": True,
    "sounds": True,
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def save(cfg: dict) -> None:
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    try:
        with open(PATH, encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = {}
    old.update(cfg)
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(old, f, indent=1, ensure_ascii=False)
    os.replace(tmp, PATH)
