"""Windows CI: what a screen reader gets from the window, read through MSAA the way NVDA,
JAWS and Narrator read it. No screen reader on the runner, so this is the nearest check.

    python tools/win_acc_check.py      (Windows; needs wxPython and comtypes)

Checks: the main window's controls carry their names (not whatever text sits before them),
and a check list row answers as a checkbox that says whether it's checked, and changes when
it's checked. Exit 0 when all hold.
"""
import ctypes
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import comtypes.client  # noqa: E402
import wx  # noqa: E402

from rplmaker import gui, speech  # noqa: E402

oleacc = comtypes.client.GetModule("oleacc.dll")
STATE_CHECKED = 0x10
ROLE_CHECKBUTTON = 0x2C


def acc_of(ctrl):
    ptr = ctypes.POINTER(oleacc.IAccessible)()
    ctypes.oledll.oleacc.AccessibleObjectFromWindow(ctrl.GetHandle(), ctypes.c_long(-4),   # OBJID_CLIENT
                                                    ctypes.byref(oleacc.IAccessible._iid_), ctypes.byref(ptr))
    return ptr


def main() -> int:
    gui.settings.save = lambda cfg: None
    app = wx.App()
    f = gui.MainFrame()
    f.Show()
    problems = []
    for ctrl, want in ((f.find, "Find"), (f.list, "Plug-ins"), (f.details, "Details"), (f.gauge, "Progress")):
        got = acc_of(ctrl).accName(0)
        print(f"{want}: named {got!r}")
        if got != want:
            problems.append(f"{want} is named {got!r}")

    for ctrl, want in ((f.b_make, "Makes a library"), (f.list, "Space checks")):
        got = acc_of(ctrl).accDescription(0) or ""
        print(f"help tag: {got[:50]!r}")
        if not got.startswith(want):
            problems.append(f"{ctrl.GetLabel() or 'the list'} has no help tag for screen readers ({got!r})")
    dlg = gui.PreferencesDialog(f, f.cfg)
    for ctrl, want in ((dlg.author, "Your name in file names"), (dlg.twice, None), (dlg.prefix, None),
                       (dlg.layout, "Folders for libraries"), (dlg.per_cat, None)):
        a = acc_of(ctrl)
        print(f"Preferences: {a.accName(0)!r}, {str(a.accDescription(0) or '')[:40]!r}")
        if want and a.accName(0) != want:
            problems.append(f"Preferences field named {a.accName(0)!r}")
        if not a.accDescription(0):
            problems.append(f"Preferences {a.accName(0)!r} has no help tag for screen readers")
    dlg.Destroy()
    # every shortcut the menus show must be a real key here too (Control on Windows)
    mb = f.GetMenuBar()
    keys_seen = {}
    for i in range(mb.GetMenuCount()):
        for item in mb.GetMenu(i).GetMenuItems():
            label = item.GetItemLabel()
            if "\t" in label and item.GetAccel() is None:
                problems.append(f"menu item {label!r} has no working shortcut")
            elif "\t" in label:
                key = item.GetAccel().ToString()
                print(f"shortcut: {label.split(chr(9))[0]!r} -> {key}")
                if key in keys_seen:
                    problems.append(f"{key} means both {keys_seen[key]!r} and {label!r}")
                keys_seen[key] = label
    for want_label, want_key in (("Preferences...", "Ctrl+P"), ("Say Progress", "Ctrl+Shift+Space")):
        got = [k for k, lab in keys_seen.items() if lab.split("\t")[0] == want_label]
        if got != [want_key]:
            problems.append(f"{want_label} has {got}, not {want_key}")
    lst = f.list
    lst.Set(["First, Maker: 12 VST3 presets", "Second, Maker: 3 VST3 presets"])
    speech.check_list(lst, "Plug-ins")
    lst.SetSelection(1)
    lst.SetFocus()
    lst.Check(1)
    speech.row_changed(lst, 1)
    a = acc_of(lst)
    for child, checked in ((1, False), (2, True)):
        name, role, state = a.accName(child), a.accRole(child), a.accState(child)
        print(f"row {child}: {name!r}, role {role}, state {state:#x}")
        if role != ROLE_CHECKBUTTON:
            problems.append(f"row {child} isn't a checkbox (role {role})")
        if bool(state & STATE_CHECKED) != checked:
            problems.append(f"row {child} says {'checked' if state & STATE_CHECKED else 'not checked'}")
        if not name or "Maker" not in str(name):
            problems.append(f"row {child} has no name")
    lst.Check(1, False)
    if a.accState(2) & STATE_CHECKED:
        problems.append("unchecking row 2 didn't change what it says")
    f.Destroy()
    print("Windows accessibility: " + ("OK" if not problems else "FAILED: " + "; ".join(problems)))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
