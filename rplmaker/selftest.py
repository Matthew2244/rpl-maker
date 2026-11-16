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
    try:   # organizing: a library copied into a folder tree, its names given their categories
        import tempfile
        from . import formats, organize
        from .inventory import Plugin
        with tempfile.TemporaryDirectory() as d:
            src, dst = os.path.join(d, "in"), os.path.join(d, "out")
            os.makedirs(src)
            with open(os.path.join(src, "T VST3 by X.RPL"), "w", encoding="utf-8") as f:
                f.write(states.rpl_text("VST3: T (V)", [("a", b"1"), ("b", b"2")]))
            p = Plugin("VST3: T (V)", "T", "V", "0" * 32, "t.vst3", False)
            p.presets["nks"] = [formats.Found("/x/a.nksf", "nks", "a", category="Bass"),
                                formats.Found("/x/b.nksf", "nks", "b", category="Lead")]
            organize.organize_folder(src, dst, [p], per_category=True, min_keep=1)
            assert sorted(os.listdir(os.path.join(dst, "V", "T"))) == ["T - Bass VST3 by X.RPL", "T - Lead VST3 by X.RPL"]
            assert organize.safe_name("CON") == "CON_"
    except Exception as e:  # noqa: BLE001
        problems.append(f"organizing: {e!r}")
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
    from . import sounds
    if sounds.missing():
        problems.append("sounds missing: " + ", ".join(sounds.missing()))
    n = len(inventory.plugins())
    print(f"REAPER's plug-in list: {n} VST3 plug-ins" if n else "REAPER's plug-in list: not found (fine on a computer without REAPER)")
    print("Self-test: " + ("OK" if not problems else "FAILED: " + "; ".join(problems)))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
