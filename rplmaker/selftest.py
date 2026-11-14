"""--self-test: what a build must be able to do, without REAPER running or a window shown.
Last line is "Self-test: OK" or what failed. build_app.py and release_mac.py read it."""
import os
import sys


def main() -> int:
    problems = []
    try:
        import wx  # noqa: F401
        from . import gui  # noqa: F401
    except Exception as e:  # noqa: BLE001
        problems.append(f"the window can't load: {e}")
    from . import inventory, portable, states
    if not os.path.isfile(portable.WORKER):
        problems.append(f"worker.lua missing at {portable.WORKER}")
    try:
        st = states.parse_state(states.payload({"prefix": b"\0" * 16, "marker": b"\xff\xff\x10\x00"}, b"x", "n"))
        assert st["comp"] == b"x"
        plug, pr = states.parse_rpl(states.rpl_text("VST3: T (V)", [("a", b"1")]))
        assert pr == [("a", b"1")]
    except Exception as e:  # noqa: BLE001
        problems.append(f"preset files: {e}")
    from . import updates
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin" and not updates._sparkle_path():
            problems.append("Sparkle.framework isn't inside the app")
        if sys.platform == "darwin" and not updates._mac_start():
            problems.append("Sparkle didn't start")
        if sys.platform == "win32" and not updates.win_dll_path():
            problems.append("WinSparkle.dll isn't beside the app")
        if sys.platform == "win32":
            try:
                ctypes = __import__("ctypes")
                ctypes.CDLL(updates.win_dll_path())
            except Exception as e:  # noqa: BLE001
                problems.append(f"WinSparkle didn't load: {e}")
            try:
                from . import speech
                speech.load_prism()
            except Exception as e:  # noqa: BLE001
                problems.append(f"Prism (screen reader speech) didn't load: {e}")
    n = len(inventory.plugins())
    print(f"REAPER's plug-in list: {n} VST3 plug-ins" if n else "REAPER's plug-in list: not found (fine on a Mac without REAPER)")
    print("Self-test: " + ("OK" if not problems else "FAILED: " + "; ".join(problems)))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
