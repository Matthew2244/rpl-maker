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
