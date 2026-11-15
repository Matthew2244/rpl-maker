"""Folder access on Windows: the counterpart of the Mac's Allow Folder Access.

Windows doesn't ask before an app opens a folder the way macOS does, so there's nothing to
allow ahead of time. What can still go wrong there: a preset folder Magpie can't read
(permissions, a drive that's gone), and the libraries folder it can't write to, most often
because Windows Security's ransomware protection (Controlled Folder Access) guards
Documents and blocks apps it doesn't know. `check` tries each for real and says, in plain
words, what's wrong and how to fix it. Matthew's rule (2026-11-15): anything a Mac user
gets, a Windows user gets the equivalent of.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

from . import APP_NAME

CFA_KEYS = (   # a policy setting wins over the person's own
    r"SOFTWARE\Policies\Microsoft\Windows Defender\Windows Defender Exploit Guard\Controlled Folder Access",
    r"SOFTWARE\Microsoft\Windows Defender\Windows Defender Exploit Guard\Controlled Folder Access",
)
CFA_STEPS = (f"Windows Security's ransomware protection is on, and it can stop apps it doesn't know from "
             f"saving in Documents. To let {APP_NAME} save there: open Windows Security, then Virus and threat "
             "protection, then Manage ransomware protection, then Allow an app through Controlled folder "
             f"access, then Add an allowed app, and choose {APP_NAME}. Or choose another folder for libraries "
             "in Settings.")


def ransomware_protection() -> str | None:
    """'on', 'audit' or 'off' for Controlled Folder Access; None when it can't be read (not
    Windows, no Defender, or another antivirus in charge). Never raises."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None
    for key in CFA_KEYS:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
                value, _ = winreg.QueryValueEx(k, "EnableControlledFolderAccess")
        except OSError:
            continue
        try:
            value = int(value)
        except (TypeError, ValueError):
            continue
        return {0: "off", 1: "on", 2: "audit", 3: "on", 4: "audit"}.get(value, "on")
    return None


@dataclass
class Report:
    readable: int = 0
    unreadable: list = field(default_factory=list)     # (folder, why)
    can_save: bool = True
    save_why: str = ""
    protection: str | None = None

    def summary(self) -> str:
        """One spoken sentence or two."""
        parts = [f"Done. {APP_NAME} read {self.readable} of {self.readable + len(self.unreadable)} preset folders"]
        parts[0] += "." if not self.unreadable else f"; {len(self.unreadable)} couldn't be read."
        parts.append("It can save libraries in your libraries folder." if self.can_save else
                     "It can't save libraries in your libraries folder.")
        if not self.can_save and self.protection == "on":
            parts.append("Windows Security's ransomware protection is probably blocking it.")
        return " ".join(parts)

    def details(self, outdir: str) -> str:
        """Everything, for a window that can be read line by line."""
        L = [self.summary(), ""]
        if not self.can_save:
            L.append(f"Libraries can't be saved in {outdir}: {self.save_why}.")
            L.append(CFA_STEPS if self.protection == "on" else
                     "Choose another folder for libraries in Settings, or check that this one exists "
                     "and that you can save files in it.")
            L.append("")
        elif self.protection == "on":
            L.append(f"Windows Security's ransomware protection is on, and {APP_NAME} could still save in your "
                     "libraries folder, so nothing needs changing.")
            L.append("")
        if self.unreadable:
            L.append("These folders couldn't be read, so presets in them aren't found:")
            L += [f"  {d}: {why}" for d, why in self.unreadable[:40]]
            if len(self.unreadable) > 40:
                L.append(f"  and {len(self.unreadable) - 40} more")
            L.append("Check that the drive is connected and that your account can open them.")
        return "\n".join(L).rstrip()

    @property
    def problems(self) -> bool:
        return bool(self.unreadable) or not self.can_save


def _why(e: OSError) -> str:
    return (e.strerror or e.__class__.__name__).rstrip(".").lower()


def check(folders, outdir: str, required=(), protection=ransomware_protection, progress=None) -> Report:
    """Read every folder, save and remove a file in outdir. A folder that doesn't exist is
    skipped (the usual places a maker might use), unless it's in `required` (the person's
    own extra folders): then it's reported."""
    folders = list(folders) + list(required)
    required = {os.path.normcase(os.path.abspath(d)) for d in required}
    r = Report(protection=protection())
    seen = set()
    for d in folders:
        key = os.path.normcase(os.path.abspath(d))
        if key in seen:
            continue
        seen.add(key)
        if progress:
            progress(d)
        try:
            os.listdir(d)
            r.readable += 1
        except FileNotFoundError:
            if key in required:
                r.unreadable.append((d, "it isn't there"))
            continue
        except OSError as e:
            r.unreadable.append((d, _why(e)))
    try:
        os.makedirs(outdir, exist_ok=True)
        probe = os.path.join(outdir, ".magpie-write-test")
        with open(probe, "w") as f:
            f.write("")
        os.remove(probe)
    except OSError as e:
        r.can_save, r.save_why = False, _why(e)
    return r
