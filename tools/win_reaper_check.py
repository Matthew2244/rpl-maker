"""Windows CI: start the checking copy of REAPER from a real REAPER and watch every window it
makes. The copy must never show a window, and must never stop to ask which audio device to
use (the first Windows user found it doing exactly that in 0.1.5).

    python tools/win_reaper_check.py "C:\\path\\to\\REAPER"

Two starts, both watched every 50 ms: first the way 0.1.5 started it (no audio setting), to
show this check can see the question at all; then the way Magpie starts it now. Passes when
the second start asked nothing, nothing stayed on screen (REAPER puts its main window up for
about a quarter of a second as it starts, too busy to obey a hide, never taking the focus),
and no REAPER was left running. CI has no REAPER licence, so the copy may stop at REAPER's evaluation window; that's
reported, never counted as the audio question.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rplmaker import portable  # noqa: E402

AUDIO_WORDS = ("audio", "device")
WATCHED: dict = {}   # (class, title) -> what a dialog said, from every watch


def on_screen(hwnd) -> bool:
    """Does the window overlap any part of any screen?"""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    r = wintypes.RECT()
    if not u.GetWindowRect(hwnd, ctypes.byref(r)):
        return False
    x, y = u.GetSystemMetrics(76), u.GetSystemMetrics(77)          # SM_X/YVIRTUALSCREEN
    w, h = u.GetSystemMetrics(78), u.GetSystemMetrics(79)          # SM_CX/CYVIRTUALSCREEN
    return r.right > x and r.left < x + w and r.bottom > y and r.top < y + h


def watch(pid_of, seconds: float):
    """Sample the copy's windows until `seconds` pass. Returns (every window seen, by
    (class, title)), the longest run of samples one window stayed visible)."""
    seen, runs, longest, said = {}, {}, {}, {}
    t0 = time.time()
    while time.time() - t0 < seconds:
        pid = pid_of()
        if pid:
            now = set()
            for hwnd, cls, title, visible in portable.win_windows(pid):
                visible = visible and on_screen(hwnd)   # shown, and somewhere a person could see it
                seen[(cls, title)] = seen.get((cls, title), False) or visible
                if cls == "#32770" and (cls, title) not in said:
                    said[(cls, title)] = portable.win_text(hwnd)
                if visible:
                    now.add(hwnd)
                    runs[hwnd] = runs.get(hwnd, 0) + 1
                    longest[(cls, title)] = max(longest.get((cls, title), 0), runs[hwnd])
            for h in list(runs):
                if h not in now:
                    runs[h] = 0
        time.sleep(0.05)
    WATCHED.update(said)
    return seen, longest


def old_start(copy_dir: str, seconds: float):
    """0.1.5's way: no audio setting, started minimised, nothing hidden until ready."""
    ini = os.path.join(copy_dir, "reaper.ini")
    with open(ini, "w") as f:
        f.write(portable.ini_text())
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 7
    proc = subprocess.Popen([portable.exe_path(copy_dir), "-cfgfile", ini, "-nosplash", "-newinst",
                             "-ignoreerrors", "-new"], cwd=copy_dir, startupinfo=si)
    try:
        return watch(lambda: proc.pid, seconds)
    finally:
        proc.kill()
        proc.wait(10)


def new_start(copy_dir: str, seconds: float):
    """Magpie's way now: Session.start, watched from another thread."""
    s = portable.Session(copy_dir, log=lambda m: print("  log:", m, flush=True))
    out, err = {}, []

    def pid_of():
        try:
            with open(os.path.join(copy_dir, "rplmaker", "pid")) as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return None

    def watcher():
        out["r"] = watch(pid_of, seconds)
    t = threading.Thread(target=watcher)
    t.start()
    try:
        s.start(timeout=seconds - 5)
        print("  the copy got ready: its startup script ran", flush=True)
        time.sleep(3)   # watch it sit there ready, too
    except portable.CheckerError as e:
        err.append(str(e))
        print("  the copy didn't get ready:", e, flush=True)
    pid = pid_of()
    s.stop()
    t.join()
    time.sleep(1)
    left = pid and portable._win_image(pid)
    return out["r"], err, left


def describe(seen, longest):
    for (cls, title), was_visible in sorted(seen.items()):
        n = longest.get((cls, title), 0)
        print(f"    {cls!r} {title!r}: " + (f"on screen for {n} samples (~{n * 50} ms)" if was_visible else "never on screen"))
        if (cls, title) in WATCHED:
            print(f"      it said: {WATCHED[(cls, title)][:300]!r}")


def asks_about_audio(seen) -> list[str]:
    return [t for (cls, t) in seen if cls == "#32770"
            and any(w in (t + " " + WATCHED.get((cls, t), "")).lower() for w in AUDIO_WORDS)]


def main() -> int:
    src = sys.argv[1]
    work = tempfile.mkdtemp(prefix="magpie-reaper-check-")
    problems = []
    try:
        resource = os.path.join(work, "resource")   # a REAPER that's never been opened: no licence
        os.makedirs(resource)
        copy_dir = os.path.join(work, "copy")
        portable.make(copy_dir, src, resource=resource)

        print("1. Started the way 0.1.5 did (no audio setting):", flush=True)
        seen, longest = old_start(copy_dir, 25)
        describe(seen, longest)
        before = asks_about_audio(seen)
        print("  asked about audio:", before or "no", flush=True)

        print("2. Started the way Magpie does now:", flush=True)
        with open(os.path.join(copy_dir, "reaper.ini")) as f:
            print("  " + "\n  ".join(l for l in f.read().splitlines() if "nag" not in l.lower()))
        (seen, longest), err, left = new_start(copy_dir, 30)
        describe(seen, longest)
        now = asks_about_audio(seen)
        if now:
            problems.append(f"it still asked about audio: {now}")
        # REAPER shows its main window as it starts, while it's too busy to obey a hide; that
        # lasts about a quarter of a second and never takes the focus. Anything on screen for
        # half a second is a window that stays (0.1.5's question stayed for good).
        lingered = [t for (c, t), n in longest.items() if n >= 10]
        if lingered:
            problems.append(f"windows stayed on screen half a second or more: {lingered}")
        flash = max(longest.values(), default=0)
        print(f"  longest any window was on screen: about {flash * 50} ms", flush=True)
        if left:
            problems.append("the copy was still running after stop")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    for p in problems:
        print("PROBLEM:", p)
    if not problems and not before:
        problems.append("the old way didn't ask about audio here, so this check can't tell the question apart")
    print("No audio question, nothing stayed on screen, nothing left running." if not problems else "FAILED")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
