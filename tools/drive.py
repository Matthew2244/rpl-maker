"""Drive the real window off-screen, the way Wavelength's tools/drive.py does.

    .venv/bin/python tools/drive.py OUTDIR [plug-in name ...]

Never activates the window (it would take VoiceOver's focus from whoever is at the Mac):
shown transparent, off-screen, without activating. Prints every control in the order
VoiceOver reaches it (creation order) with the name VoiceOver gets, its value and its help
tag; then the list rows; then, if names are given, checks those plug-ins, makes their
libraries and prints every spoken line, the rows and the details as a listener would get them.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
out = os.path.abspath(sys.argv[1])
wanted = sys.argv[2:]

import wx  # noqa: E402
from rplmaker import gui, inventory, speech  # noqa: E402

said = []
gui.say = lambda t, polite=True: said.append(("polite" if polite else "URGENT", t))
gui.settings.save = lambda cfg: None          # never touch the real settings from a test
import time as _t  # noqa: E402
from rplmaker import sounds as _sounds  # noqa: E402
_sounds._start = lambda p: said.append(("SOUND", os.path.basename(p) + f" at {_t.monotonic():.2f}"))   # recorded, never played
_said_raw = gui.say
gui.say = lambda t, polite=True: said.append(("polite" if polite else "URGENT", t + f" at {_t.monotonic():.2f}"))


def ax_label(ctrl):
    """What the control itself answers VoiceOver with (accessibilityLabel)."""
    try:
        ctypes, objc, send, nsstr = speech._objc()
        v = ctrl.GetHandle()
        lab = send(v, "accessibilityLabel")
        if not lab and send(v, "respondsToSelector:", objc.sel_registerName(b"documentView"),
                            restype=ctypes.c_bool, argtypes=(ctypes.c_void_p,)):
            lab = send(send(v, "documentView"), "accessibilityLabel")
        if not lab:
            return ""
        return ctypes.string_at(send(lab, "UTF8String")).decode()
    except Exception:  # noqa: BLE001
        return "?"


def walk(win, depth=0):
    for c in win.GetChildren():
        kind = type(c).__name__
        if isinstance(c, wx.Panel) and not isinstance(c, (wx.SearchCtrl,)):
            walk(c, depth)
            continue
        if isinstance(c, wx.StaticText):
            print(f"  text: {c.GetLabel()!r}")
            continue
        value = ""
        if isinstance(c, (wx.TextCtrl, wx.SearchCtrl)):
            value = c.GetValue()[:60]
        elif isinstance(c, wx.Choice):
            value = c.GetStringSelection()
        elif isinstance(c, wx.CheckBox):
            value = "checked" if c.GetValue() else "unchecked"
        elif isinstance(c, wx.SpinCtrl):
            value = str(c.GetValue())
        elif isinstance(c, wx.Gauge):
            value = f"{c.GetValue()}%"
        name = c.GetLabel() if isinstance(c, (wx.Button, wx.CheckBox)) else ax_label(c)
        tip = c.GetToolTipText() if c.GetToolTip() else "NO HELP TAG"
        en = "" if c.IsEnabled() else " (dimmed)"
        print(f"  {kind}: name {name!r}{en}, value {value!r}\n      help: {tip}")


def pump(seconds, until=None):
    end = time.time() + seconds
    while time.time() < end:
        wx.GetApp().Yield(True)   # the real event loop's work, briefly
        time.sleep(0.05)
        if until and until():
            return True
    return False


app = wx.App(False)
# Background-only: this process can never become the active app, so it can't take the focus
# (or VoiceOver's attention) from whoever is using the Mac. 2 = NSApplicationActivationPolicyProhibited.
_c, _o, _send, _ns = speech._objc()
_send(_send(_o.objc_getClass(b"NSApplication"), "sharedApplication"), "setActivationPolicy:", 2,
      restype=_c.c_bool, argtypes=(_c.c_long,))
f = gui.MainFrame()
f.cfg["out_dir"] = out
f.cfg["checked"] = []
f.cfg["access_asked"] = True   # the first-run folder question is a real alert: never from a test
f.checked = set()
f.SetPosition((-3000, -3000))
f.SetTransparent(0)
f.ShowWithoutActivating()
t0 = time.time()
pump(180, lambda: f.busy is None and f.plugs)
print(f"Scan took {time.time() - t0:.0f}s")
print("\nMain window, in reading order:")
walk(f)
print("\nFirst rows:")
for i in range(min(8, f.list.GetCount())):
    print("  ", f.list.GetString(i))
print("\nSpoken so far:", said)

if wanted:
    for want in wanted:
        w = inventory.norm(want)
        hit = [p for p in f.plugs if inventory.norm(p.name) == w]
        for p in hit:
            f.checked.add(p.class_id)
    f.refill()
    f.show.SetSelection(2)       # Checked plug-ins
    f.refill()
    print("\nChecked view:")
    for i in range(f.list.GetCount()):
        print("  ", f.list.GetString(i), "(checked)" if f.list.IsChecked(i) else "")
    print("  count:", f.count.GetLabel())
    said.clear()
    f.on_make()
    stop_at = float(os.environ.get("DRIVE_STOP", "0"))
    if stop_at:    # press Stop part way through, as a person would
        pump(stop_at)
        print(f"\n(pressing Stop after {stop_at:.0f} s; status was: {f.status.GetLabel()})")
        f.on_stop()
    pump(3600, lambda: f.busy is None)
    pump(12)   # sounds and speech queue one at a time: let the last ones happen
    print("\nSpoken during the run:")
    for kind, t in said:
        print(f"  [{kind}] {t}")
    print("\nRows after:")
    for i in range(f.list.GetCount()):
        print("  ", f.list.GetString(i))
    for i in range(f.list.GetCount()):
        f.list.SetSelection(i)
        f.show_details()
        print("\nDetails:\n" + f.details.GetValue())
    print("\nStatus:", f.status.GetLabel())
    print("Report:", f.last_report)
f.Destroy()
