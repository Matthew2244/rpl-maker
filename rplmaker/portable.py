"""The checking copy of REAPER: a separate, hidden copy that never touches your own.

It lives in this app's support folder with its own reaper.ini, its own presets folder and
its own scripts. From your REAPER it only *reads* two files, copied once: the licence (so
the copy doesn't stop at the evaluation screen) and the plug-in list (so it doesn't have to
scan every plug-in again). Your REAPER, its settings and its presets are never written.

On the Mac the copy is renamed (its own bundle id and program name, signed for this
computer only) so it can never be mistaken for your REAPER: not by macOS, which would
otherwise bring your REAPER forward instead of opening a second one, and not by anything
that looks for a running REAPER by name. On Windows REAPER runs portable when a reaper.ini
sits beside reaper.exe, so the copy is simply REAPER's program folder copied, started
minimised and found again by its own pid file.

`Session` starts it hidden, hands it jobs through files, and notices when it hangs or a
plug-in takes it down, so one bad plug-in costs that plug-in, never the run.
"""
from __future__ import annotations

import os
import plistlib
import shutil
import signal
import subprocess
import time

from . import inventory

WIN = inventory.WIN
SUPPORT = inventory.SUPPORT
COPY_DIR = os.path.join(SUPPORT, "checking-reaper")
APP_NAME = "REAPER for checking presets"
EXE = "REAPERCheck"
BUNDLE_ID = "com.cockos.reaper.rplmaker-check"
SOURCE_APP = "/Applications/REAPER.app"
LOCK = os.path.join(SUPPORT, "checking.lock")


def find_reaper() -> str | None:
    """Where REAPER is. Mac: /Applications first, then ~/Applications, then wherever Spotlight
    knows an app with REAPER's bundle id (renamed, or in a folder of its own). Windows: the
    folder holding reaper.exe, from the installer's registry entry or the usual places."""
    if WIN:
        return _find_reaper_windows()
    for p in (SOURCE_APP, os.path.join(inventory.HOME, "Applications", "REAPER.app")):
        if os.path.isdir(p):
            return p
    try:
        r = subprocess.run(["mdfind", "kMDItemCFBundleIdentifier == 'com.cockos.reaper'"],
                           capture_output=True, text=True, timeout=10)
        for line in r.stdout.splitlines():
            if line.endswith(".app") and os.path.isdir(line) and not line.startswith(("/private/", "/Volumes/")) \
                    and SUPPORT not in line:
                return line
    except Exception:  # noqa: BLE001
        pass
    return None
WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worker.lua")

INI = """[REAPER]
autosaveint=0
autosavemode=0
loadlastproj=0
newprojdo=0
splash=0
splash2=0
verchk=0
undomaxmem=0
mixwnd_vis=0
fxadd_show=0
vstfullstate=33605
vstpath_arm64=/Library/Audio/Plug-Ins/VST3;~/Library/Audio/Plug-Ins/VST3
vstpath64=/Library/Audio/Plug-Ins/VST3;~/Library/Audio/Plug-Ins/VST3
"""
if WIN:
    INI = INI.replace("vstpath_arm64=/Library/Audio/Plug-Ins/VST3;~/Library/Audio/Plug-Ins/VST3\n", "") \
             .replace("vstpath64=/Library/Audio/Plug-Ins/VST3;~/Library/Audio/Plug-Ins/VST3\n",
                      "vstpath64=%CommonProgramFiles%\\VST3\n")


def _find_reaper_windows() -> str | None:
    tries = []
    try:
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for key in (r"SOFTWARE\REAPER", r"SOFTWARE\WOW6432Node\REAPER"):
                try:
                    with winreg.OpenKey(root, key) as k:
                        tries.append(winreg.QueryValueEx(k, "")[0])
                except OSError:
                    pass
    except ImportError:
        pass
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    tries += [os.path.join(pf, "REAPER (x64)"), os.path.join(pf, "REAPER (ARM64)"), os.path.join(pf, "REAPER")]
    for d in tries:
        if d and os.path.isfile(os.path.join(d, "reaper.exe")) and SUPPORT not in d:
            return d
    return None


class CheckerError(Exception):
    pass


def quiet_device() -> str | None:
    """An output device for the copy to name. REAPER asks which audio device to use on its
    first run unless it's given one that exists, and that question would stop it. Nothing it
    does is ever heard: the worker mutes the master and the track before any plug-in loads.
    Still, an output-only device that isn't the main one is chosen when there is one, so
    nothing could reach the speakers in use; output-only also means it never opens a
    microphone, which would make macOS ask for permission."""
    try:
        r = subprocess.run(["system_profiler", "SPAudioDataType", "-json"], capture_output=True, text=True, timeout=30)
        import json
        items = [it for g in json.loads(r.stdout).get("SPAudioDataType", []) for it in g.get("_items", [])]
    except Exception:  # noqa: BLE001
        return None
    outs = [it for it in items if it.get("coreaudio_device_output")]
    def rank(it):
        only = not it.get("coreaudio_device_input")
        main = it.get("coreaudio_default_audio_output_device") == "spaudio_yes"
        return (not only, main)
    outs.sort(key=rank)
    return outs[0]["_name"] if outs else None


def your_vst_paths(resource: str | None = None) -> dict:
    """The plug-in folders your own REAPER looks in, when you've set any (Preferences, VST),
    from its reaper.ini: {"vstpath64": ..., "vstpath_arm64": ...}. The plug-in list the copy
    is given names files, not folders, so the copy must look in the same folders as your
    REAPER or a plug-in kept somewhere else (another drive, a custom folder) can't be loaded."""
    resource = resource or inventory.REAPER_RESOURCE
    out = {}
    try:
        with open(os.path.join(resource, "reaper.ini"), encoding="utf-8", errors="replace") as f:
            section = ""
            for line in f:
                line = line.strip()
                if line.startswith("["):
                    section = line.lower()
                elif section == "[reaper]" and "=" in line:
                    k, _, v = line.partition("=")
                    if k in ("vstpath64", "vstpath_arm64") and v.strip():
                        out[k] = v.strip()
    except OSError:
        pass
    return out


def ini_text(resource: str | None = None) -> str:
    """The copy's reaper.ini: this app's settings, with your REAPER's plug-in folders when
    you've set any, Windows variables like %CommonProgramFiles% spelled out."""
    lines = []
    yours = your_vst_paths(resource)
    for line in INI.splitlines():
        k, sep, v = line.partition("=")
        if k in yours:
            v = yours.pop(k)
        if k.startswith("vstpath"):
            v = os.path.expandvars(v)
        lines.append(f"{k}={v}" if sep else line)
    lines += [f"{k}={os.path.expandvars(v)}" for k, v in yours.items()]
    return "\n".join(lines) + "\n"


def write_ini(copy_dir: str = COPY_DIR) -> None:
    text = ini_text()
    dev = None if WIN else quiet_device()
    if dev:
        text += f"coreaudiobs=512\ncoreaudiobsuse=1\ncoreaudiosrateuse=0\ncoreaudioindevnew={dev}\ncoreaudiooutdevnew={dev}\n"
    with open(os.path.join(copy_dir, "reaper.ini"), "w") as f:
        f.write(text)


def app_path(copy_dir: str = COPY_DIR) -> str:
    return copy_dir if WIN else os.path.join(copy_dir, APP_NAME + ".app")


def exe_path(copy_dir: str = COPY_DIR) -> str:
    if WIN:
        return os.path.join(copy_dir, "reaper.exe")
    return os.path.join(app_path(copy_dir), "Contents", "MacOS", EXE)


def source_version(src: str | None = None) -> str | None:
    src = src or find_reaper()
    if not src:
        return None
    if WIN:   # the program's own file version: reaper.exe changes with every release
        try:
            st = os.stat(os.path.join(src, "reaper.exe"))
            return f"{st.st_size}-{int(st.st_mtime)}"
        except OSError:
            return None
    try:
        with open(os.path.join(src, "Contents", "Info.plist"), "rb") as f:
            return plistlib.load(f).get("CFBundleShortVersionString")
    except OSError:
        return None


def status(copy_dir: str = COPY_DIR, src: str | None = None) -> str:
    """'missing' (no REAPER at all), 'none' (not made yet), 'stale' (REAPER updated since), 'ready'."""
    src = src or find_reaper()
    if not src or not os.path.isdir(src):
        return "missing"
    if not os.path.exists(exe_path(copy_dir)):
        return "none"
    try:
        with open(os.path.join(copy_dir, "made-from.txt")) as f:
            if f.read().strip() != (source_version(src) or ""):
                return "stale"
    except OSError:
        return "stale"
    return "ready"


def make(copy_dir: str = COPY_DIR, src: str | None = None, resource: str = inventory.REAPER_RESOURCE,
         progress=None) -> None:
    """Make (or remake) the checking copy. Reads your REAPER; writes only inside copy_dir."""
    src = src or find_reaper()
    if not src or not os.path.isdir(src):
        raise CheckerError("REAPER isn't installed on this computer, so there's nothing to check presets with.")
    try:
        _make(copy_dir, src, resource, progress or (lambda s: None))
    except (OSError, subprocess.CalledProcessError) as e:
        # plain words, not a command line: usually a full disk or a REAPER being updated
        why = getattr(e, "strerror", None) or "copying or signing it failed"
        raise CheckerError(f"Couldn't make the checking copy of REAPER: {why}. Check there's free space, "
                           "and that REAPER isn't being updated, then try again.") from e


def _make(copy_dir, src, resource, say) -> None:
    os.makedirs(copy_dir, exist_ok=True)
    if WIN:
        say("Copying REAPER")
        shutil.copytree(src, copy_dir, dirs_exist_ok=True)
        _finish_copy(copy_dir, src, resource)
        say("Ready")
        return
    app = app_path(copy_dir)
    if os.path.isdir(app):
        shutil.rmtree(app)
    say("Copying REAPER")
    subprocess.run(["ditto", src, app], check=True)
    # its own name and identity
    info = os.path.join(app, "Contents", "Info.plist")
    with open(info, "rb") as f:
        pl = plistlib.load(f)
    old_exe = pl.get("CFBundleExecutable", "REAPER")
    os.rename(os.path.join(app, "Contents", "MacOS", old_exe), os.path.join(app, "Contents", "MacOS", EXE))
    pl["CFBundleExecutable"] = EXE
    pl["CFBundleIdentifier"] = BUNDLE_ID
    pl["CFBundleName"] = APP_NAME
    pl["CFBundleDisplayName"] = APP_NAME
    pl["LSUIElement"] = True  # no Dock icon, no menu bar: it never takes the focus from you
    with open(info, "wb") as f:
        plistlib.dump(pl, f)
    say("Signing the copy for this computer")
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", app], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["xattr", "-dr", "com.apple.quarantine", app], stderr=subprocess.DEVNULL)
    # its own settings, and what it may read from yours
    _finish_copy(copy_dir, src, resource)
    say("Ready")


def _finish_copy(copy_dir, src, resource):
    write_ini(copy_dir)
    for name in ("reaper-license.rk",):
        p = os.path.join(resource, name)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(copy_dir, name))
    cache = inventory.cache_file(resource)
    if cache:
        shutil.copy2(cache, os.path.join(copy_dir, os.path.basename(cache)))
    for d in ("Scripts", "presets", "rplmaker/jobs"):
        os.makedirs(os.path.join(copy_dir, d), exist_ok=True)
    with open(os.path.join(copy_dir, "made-from.txt"), "w") as f:
        f.write(source_version(src) or "")


WAITING_WORDS = ("The checking copy of REAPER is waiting on the plug-in. macOS may be asking whether "
                 "REAPER for checking presets can open files in a folder or on a drive. If it is, choose "
                 "Allow; it carries on by itself. File, Allow Folder Access asks about every place at once.")
if WIN:   # Windows asks nothing about folders; a plug-in's own window is what holds it up there
    WAITING_WORDS = ("The checking copy of REAPER is waiting on the plug-in. It may be showing a window of its "
                     "own, such as an activation. If that closes, checking carries on by itself; if not, it "
                     "gives up on that plug-in after 4 minutes.")


def protected_folders() -> list[str]:
    """Places plug-ins keep content that macOS asks about separately for each app. Windows
    asks nothing of the kind, so there are none there."""
    if WIN:
        return []
    h = inventory.HOME
    out = [os.path.join(h, d) for d in ("Documents", "Desktop", "Music", "Downloads")]
    try:
        for v in sorted(os.listdir("/Volumes")):
            p = os.path.join("/Volumes", v)
            if os.path.isdir(p) and not os.path.islink(p) and not v.startswith("."):
                out.append(p)
    except OSError:
        pass
    return [p for p in out if os.path.isdir(p)]


def _kill(pid: int) -> None:
    """End a process outright. Windows: TerminateProcess (os.kill with any signal does that
    there, and signal.SIGKILL doesn't exist)."""
    try:
        if WIN:
            os.kill(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _win_image(pid: int) -> str | None:
    """The full path of a running Windows process's program, or None if it isn't running.
    Never os.kill(pid, 0) on Windows: that terminates the process."""
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000 | 0x0400, False, pid)   # QUERY_LIMITED_INFORMATION | QUERY_INFORMATION
    if not h:
        return None
    try:
        code = wintypes.DWORD()
        if k.GetExitCodeProcess(h, ctypes.byref(code)) and code.value != 259:   # 259: STILL_ACTIVE
            return None
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buf))
        if not k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return None
        return buf.value
    finally:
        k.CloseHandle(h)


def _win_hide(pid: int) -> int:
    """Hide the checking copy's own windows, so it's out of the taskbar and Alt-Tab the way
    the Mac's copy is out of the Dock and Command-Tab (no one should land in it thinking it's
    their REAPER). Only windows that are visible now, at start, before any plug-in loads: a
    plug-in's own window (an activation) appears later and stays visible. Never raises."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        hidden = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def each(hwnd, _lparam):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid and user32.IsWindowVisible(hwnd):
                user32.ShowWindow(hwnd, 0)   # SW_HIDE
                hidden.append(hwnd)
            return True
        user32.EnumWindows(each, 0)
        return len(hidden)
    except Exception:  # noqa: BLE001
        return 0


def _inside(path: str, root: str) -> bool:
    return os.path.realpath(path).startswith(os.path.realpath(root) + os.sep)


class Session:
    """One run of the checking copy. Use as a context manager; always ends the copy it started."""

    def __init__(self, copy_dir: str = COPY_DIR, log=None):
        self.dir = copy_dir
        self.jobs = os.path.join(copy_dir, "rplmaker", "jobs")
        self.pid = None
        self.n = 0
        self.log = log or (lambda s: None)
        self.closed = False   # set by close(): never start the copy again

    # -- start and stop -------------------------------------------------------------------
    def _find_pid(self):
        if WIN:   # the pid file, believed only if that process really is this copy's reaper.exe
            try:
                with open(os.path.join(self.dir, "rplmaker", "pid")) as f:
                    pid = int(f.read().strip())
            except (OSError, ValueError):
                return None
            img = _win_image(pid)
            return pid if img and os.path.normcase(img) == os.path.normcase(exe_path(self.dir)) else None
        r = subprocess.run(["pgrep", "-f", exe_path(self.dir)], capture_output=True, text=True)
        pids = [int(x) for x in r.stdout.split()]
        return pids[0] if pids else None

    def start(self, timeout: float = 90) -> None:
        if self.closed:
            raise CheckerError("stopped")
        left = self._find_pid()
        if left:
            # Only one run at a time holds the lock (Builder.build), so a copy running now is
            # left over from a run that ended badly (the app quit or crashed): end it.
            _kill(left)
            time.sleep(0.5)
        os.makedirs(self.jobs, exist_ok=True)
        for f in os.listdir(self.jobs):
            os.remove(os.path.join(self.jobs, f))
        ready = os.path.join(self.dir, "rplmaker", "ready")
        if os.path.exists(ready):
            os.remove(ready)
        # the worker lives beside the copy, so the copy never reads from inside this app (which
        # may move, or be replaced by an update while a run is going)
        worker = os.path.join(self.dir, "rplmaker", "worker.lua")
        shutil.copyfile(WORKER, worker)
        with open(os.path.join(self.dir, "Scripts", "__startup.lua"), "w") as f:
            f.write('dofile("%s")\n' % worker.replace("\\", "\\\\").replace('"', '\\"'))
        write_ini(self.dir)   # devices come and go; name one that's here today
        cache = inventory.cache_file()
        if cache:   # your REAPER's plug-in list as it is today, so the copy has nothing new to scan
            try:
                shutil.copy2(cache, os.path.join(self.dir, os.path.basename(cache)))
            except OSError:
                pass
        ini = os.path.join(self.dir, "reaper.ini")
        args = ["-cfgfile", ini, "-nosplash", "-newinst", "-ignoreerrors", "-new"]
        if WIN:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 7   # SW_SHOWMINNOACTIVE: minimised, and never takes the focus
            proc = subprocess.Popen([exe_path(self.dir)] + args, cwd=self.dir, startupinfo=si)
            with open(os.path.join(self.dir, "rplmaker", "pid"), "w") as f:
                f.write(str(proc.pid))
        else:
            subprocess.run(["open", "-n", "-g", "-j", "-a", app_path(self.dir), "--args"] + args, check=True)
        t0 = time.time()
        while time.time() - t0 < timeout:
            if os.path.exists(ready):
                self.pid = self._find_pid()
                if WIN and self.pid:
                    _win_hide(self.pid)
                self.log(f"checking REAPER ready after {time.time() - t0:.0f}s, pid {self.pid}")
                return
            time.sleep(0.3)
        self.stop()
        if not os.path.exists(os.path.join(self.dir, "reaper-license.rk")):
            raise CheckerError("The checking copy of REAPER didn't start. REAPER has no licence on this computer, "
                               "so the copy stops at REAPER's evaluation window, and this needs a licensed REAPER.")
        raise CheckerError("The checking copy of REAPER didn't start within 90 seconds. A window may be "
                           f"waiting in it (a question from {'Windows' if WIN else 'macOS'} or REAPER); it has "
                           "been closed.")

    def stop(self) -> None:
        pid = self.pid or self._find_pid()
        if pid:
            _kill(pid)   # only ever the copy this app made and started
        self.pid = None
        try:
            os.remove(os.path.join(self.dir, "Scripts", "__startup.lua"))
        except OSError:
            pass

    def close(self) -> None:
        """End the copy for good: a run being stopped or the app quitting. Any job waiting on
        it ends with CheckerError('stopped') instead of starting it again."""
        self.closed = True
        self.stop()

    def alive(self) -> bool:
        if not self.pid:
            return False
        if WIN:
            return _win_image(self.pid) is not None
        try:
            os.kill(self.pid, 0)
            return True
        except ProcessLookupError:
            return False

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *a):
        self.stop()

    # -- jobs -----------------------------------------------------------------------------
    def run(self, line: str, quiet_limit: float = 60, on_line=None, on_wait=None, wait_after: float = 8) -> list[str]:
        """Hand the copy one job and wait for it. `quiet_limit` is how long it may go without
        writing anything before it counts as stuck. Returns the output lines (without END).
        Raises CheckerError('crashed'/'stuck') after ending the copy."""
        if not self.alive():
            self.start()
        self.n += 1
        base = os.path.join(self.jobs, f"job-{self.n}")
        with open(base + ".tmp", "w", encoding="utf-8") as f:
            f.write(line + "\n")
        os.rename(base + ".tmp", base + ".txt")
        out, done = base + ".out", base + ".done"
        last_size, last_change, seen = -1, time.time(), 0
        waited = False
        while not os.path.exists(done):
            time.sleep(0.2)
            size = os.path.getsize(out) if os.path.exists(out) else 0
            if size != last_size:
                last_size, last_change = size, time.time()
                if on_line and size:
                    with open(out, encoding="utf-8", errors="replace") as f:
                        lines = f.read().split("\n")[:-1]
                    for l in lines[seen:]:
                        on_line(l)
                    seen = len(lines)
            if self.closed:
                raise CheckerError("stopped")
            if not self.alive():
                self.pid = None
                raise CheckerError("crashed")
            if on_wait and not waited and time.time() - last_change > wait_after:
                waited = True
                on_wait()
            if time.time() - last_change > quiet_limit:
                self.stop()
                raise CheckerError("stuck")
        with open(out, encoding="utf-8", errors="replace") as f:
            lines = f.read().split("\n")
        for leftover in (out, done):   # a big library's output runs to megabytes; don't keep it
            try:
                os.remove(leftover)
            except OSError:
                pass
        if on_line:
            for l in lines[seen:]:
                if l:
                    on_line(l)
        return [l for l in lines if l and l != "END"]

    def capture(self, fx: str, on_wait=None) -> dict:
        # long: the first time a plug-in opens a protected folder, macOS stops it there until
        # the person answers whether this copy may (see WAITING_WORDS)
        lines = self.run("CAPTURE\t" + fx, quiet_limit=240, on_wait=on_wait)
        if not lines or lines[0] == "ADDFAIL":
            raise CheckerError("addfail")
        d = {}
        for l in lines:
            k, _, v = l.partition("\t")
            d[k] = v
        return d

    def write_presets(self, file_name: str, text: str) -> str:
        """Put a preset file where the checking copy looks for this plug-in's presets."""
        path = os.path.join(self.dir, "presets", os.path.basename(file_name))
        if not _inside(path, self.dir):
            raise CheckerError("refusing to write outside the checking copy")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path
