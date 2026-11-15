"""The four sounds Matthew picked by ear (2026-11-14), and playing them without getting in the
way of the screen reader.

    done           the whole run finished          synth pluck, take 1
    failed         a library couldn't be made      synth pluck, take 1
    library_made   one library made                synth pluck, take 2
    waiting        it's waiting on you             marimba, take 2

Files: assets/sounds/<event>.mp3 (Mac, afplay) and .wav (Windows, winsound), made by
tools/finish_sounds.py. Rules: sounds never overlap (a second waits for the first to end);
library_made plays at most every 2 seconds, so a run of small libraries isn't a drum roll;
and `play` returns when its sound will be over, so the window can say its sentence after
it, never on top of it. Preferences, Play sounds turns them off. A missing file is silence,
never an error.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

EVENTS = ("done", "failed", "library_made", "waiting")
LENGTH = {"done": 0.73, "failed": 1.32, "library_made": 0.64, "waiting": 1.24}   # seconds, from the files
GAP = 0.15                     # between one sound's end and the next's start
MIN_EVERY = {"library_made": 2.0}

_state = {"busy_until": 0.0, "last": {}, "lock": threading.Lock()}


def folder() -> str:
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", "sounds")


def path(event: str) -> str:
    return os.path.join(folder(), event + (".wav" if sys.platform == "win32" else ".mp3"))


def _start(p: str) -> None:
    try:
        if sys.platform == "win32":
            import winsound
            winsound.PlaySound(p, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        elif sys.platform == "darwin":
            subprocess.Popen(["afplay", p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
    except Exception:  # noqa: BLE001 - a sound failing must never stop anything
        pass


def play(event: str, enabled: bool = True) -> float:
    """Play a sound, after any still playing. Returns seconds from now until it has finished
    (0 when nothing plays), for speech to wait that long."""
    p = path(event)
    if not enabled or event not in LENGTH or not os.path.exists(p):
        return 0.0
    with _state["lock"]:
        now = time.monotonic()
        last = _state["last"].get(event, -1e9)
        if now - last < MIN_EVERY.get(event, 0):
            return max(0.0, _state["busy_until"] - now)
        start = max(now, _state["busy_until"] + GAP if _state["busy_until"] > now else now)
        _state["last"][event] = start
        _state["busy_until"] = start + LENGTH[event]
    delay = start - now
    if delay <= 0.01:
        _start(p)
    else:
        threading.Timer(delay, _start, args=(p,)).start()
    return delay + LENGTH[event]


def missing() -> list[str]:
    return [e for e in EVENTS if not os.path.exists(path(e))]
