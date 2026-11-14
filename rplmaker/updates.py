"""Updates: Sparkle on the Mac, WinSparkle on Windows, from Wavelength and XK-7D Companion.

Matthew's rule, both systems: updates are heard, never popped up. Neither updater checks by
itself. The app looks at the update list 15 seconds after it opens and every 4 hours while
it's open, and when a newer version is out it says so once per version, politely, only when
the app is in front. Help, Check for Updates opens Sparkle's or WinSparkle's own window:
what's new, Install, Skip This Version, Remind Me Later.

Every update is signed with this app's own EdDSA key (Studio login Keychain, Sparkle's
generate_keys, account rpl-maker); its public half is below and in Info.plist. A copy run
from source, or a Windows copy that wasn't installed, has no updater: Check for Updates
opens the releases page instead.
"""
from __future__ import annotations

import ctypes
import os
import re
import sys
import urllib.request

from . import APP_NAME, VERSION

REPO = "https://github.com/Matthew2244/rpl-maker"
FEED_MAC = REPO + "/releases/latest/download/appcast.xml"
FEED_WIN = REPO + "/releases/latest/download/appcast-windows.xml"
PUBLIC_KEY = "jTFOt+znz5fHM/9/JsRJfm5aaz7S3XDQ+st0AMWacYk="

_state = {"mac": None, "win_dll": None, "win_cb": None, "failed": False}


def version_tuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:4])


def newest(feed: str | None = None, timeout: float = 15) -> str | None:
    """The newest version in the update list, or None when it can't be read (offline, or no
    release yet). Never raises."""
    feed = feed or (FEED_WIN if sys.platform == "win32" else FEED_MAC)
    try:
        req = urllib.request.Request(feed, headers={"User-Agent": f"{APP_NAME}/{VERSION}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read(200_000).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return None
    vs = re.findall(r"<sparkle:shortVersionString>([^<]+)</sparkle:shortVersionString>", text)
    return max(vs, key=version_tuple) if vs else None


def is_newer(v: str | None) -> bool:
    return bool(v) and version_tuple(v) > version_tuple(VERSION)


# ---- Mac: Sparkle.framework in Contents/Frameworks, through the Objective-C runtime ---------

def _objc():
    import ctypes.util
    objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]

    def send(obj, sel, *args, restype=ctypes.c_void_p, argtypes=()):
        f = objc.objc_msgSend
        f.restype = restype
        f.argtypes = [ctypes.c_void_p, ctypes.c_void_p, *argtypes]
        return f(obj, objc.sel_registerName(sel.encode()), *args)

    def nsstr(text):
        return send(objc.objc_getClass(b"NSString"), "stringWithUTF8String:", text.encode(), argtypes=(ctypes.c_char_p,))
    return objc, send, nsstr


def _sparkle_path() -> str | None:
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return None
    exe = os.path.realpath(sys.executable)
    path = os.path.join(os.path.dirname(os.path.dirname(exe)), "Frameworks", "Sparkle.framework")
    return path if os.path.isdir(path) else None


def _mac_start() -> bool:
    if _state["mac"] is not None:
        return True
    path = _sparkle_path()
    if not path:
        return False
    try:
        objc, send, nsstr = _objc()
        bundle = send(objc.objc_getClass(b"NSBundle"), "bundleWithPath:", nsstr(path), argtypes=(ctypes.c_void_p,))
        if not bundle or not send(bundle, "load", restype=ctypes.c_bool):
            return False
        cls = objc.objc_getClass(b"SPUStandardUpdaterController")
        if not cls:
            return False
        ctrl = send(send(cls, "alloc"), "initWithStartingUpdater:updaterDelegate:userDriverDelegate:", True, None, None,
                    argtypes=(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p))
        if not ctrl:
            return False
        updater = send(ctrl, "updater")
        if updater:   # the app does the looking and says so; Sparkle's window only when asked
            send(updater, "setAutomaticallyChecksForUpdates:", False, restype=None, argtypes=(ctypes.c_bool,))
        _state["mac"] = ctrl
        return True
    except Exception:  # noqa: BLE001 - updates failing must never stop the app
        return False


# ---- Windows: WinSparkle.dll beside the app, only in an installed copy ---------------------

def _win_dir() -> str | None:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return None
    return os.path.dirname(os.path.abspath(sys.executable))


def win_installed() -> bool:
    """A copy put there by the installer has an uninstaller beside it. WinSparkle updates by
    running the new installer, so only such a copy can update itself."""
    d = _win_dir()
    return bool(d) and any(n.lower().startswith("unins") and n.lower().endswith(".exe") for n in os.listdir(d))


def win_dll_path() -> str | None:
    d = _win_dir()
    if not d:
        return None
    for root, _dirs, files in os.walk(d):
        if "WinSparkle.dll" in files:
            return os.path.join(root, "WinSparkle.dll")
    return None


def _win_start(on_shutdown) -> bool:
    if _state["win_cb"] is not None:
        return True
    if not win_installed():
        return False
    path = win_dll_path()
    if not path:
        return False
    try:
        dll = ctypes.CDLL(path)
        dll.win_sparkle_set_appcast_url.argtypes = [ctypes.c_char_p]
        dll.win_sparkle_set_eddsa_public_key.argtypes = [ctypes.c_char_p]
        dll.win_sparkle_set_eddsa_public_key.restype = ctypes.c_int
        dll.win_sparkle_set_app_details.argtypes = [ctypes.c_wchar_p] * 3
        can = ctypes.CFUNCTYPE(ctypes.c_int)(lambda: 1)
        shut = ctypes.CFUNCTYPE(None)(on_shutdown)
        _state["win_cb"] = (can, shut)   # alive for as long as WinSparkle may call them
        dll.win_sparkle_set_appcast_url(FEED_WIN.encode())
        if dll.win_sparkle_set_eddsa_public_key(PUBLIC_KEY.encode()) != 1:
            return False
        dll.win_sparkle_set_app_details("Matthew Whitaker", APP_NAME, VERSION)
        dll.win_sparkle_set_can_shutdown_callback(can)
        dll.win_sparkle_set_shutdown_request_callback(shut)
        dll.win_sparkle_set_automatic_check_for_updates(0)
        dll.win_sparkle_init()
        _state["win_dll"] = dll
        return True
    except Exception:  # noqa: BLE001
        return False


# ---- both -------------------------------------------------------------------------------

def start(on_shutdown=lambda: None) -> bool:
    """Start the updater (main thread, after the window exists). False when there's none."""
    if _state["failed"]:
        return False
    ok = _win_start(on_shutdown) if sys.platform == "win32" else _mac_start()
    if not ok:
        _state["failed"] = True
    return ok


def check_with_window() -> bool:
    """Help, Check for Updates. False when there's no updater (then open the releases page)."""
    try:
        if sys.platform == "win32" and _state["win_dll"] is not None:
            _state["win_dll"].win_sparkle_check_update_with_ui()
            return True
        if _state["mac"] is not None:
            objc, send, nsstr = _objc()
            send(_state["mac"], "checkForUpdates:", None, restype=None, argtypes=(ctypes.c_void_p,))
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def cleanup() -> None:
    if _state["win_dll"] is not None:
        try:
            _state["win_dll"].win_sparkle_cleanup()
        except Exception:  # noqa: BLE001
            pass
