"""Talking to VoiceOver without moving the focus, and naming controls for it. From Wavelength.

`announce(text, polite)`: polite waits for what VoiceOver is already saying (medium
priority); news someone is waiting on (a failure, the end of a run) cuts in. Everything said
here is also shown in the window's status line, so nothing depends on speech working.
"""
from __future__ import annotations

import sys


def _objc():
    import ctypes
    import ctypes.util
    objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]

    def send(obj, sel, *args, restype=ctypes.c_void_p, argtypes=()):
        f = objc.objc_msgSend
        f.restype = restype
        f.argtypes = [ctypes.c_void_p, ctypes.c_void_p, *argtypes]
        return f(obj, objc.sel_registerName(sel.encode()), *args)

    def nsstr(t):
        return send(objc.objc_getClass(b"NSString"), "stringWithUTF8String:", t.encode(), argtypes=(ctypes.c_char_p,))
    return ctypes, objc, send, nsstr


def label(ctrl, text: str) -> None:
    """The control's spoken name on the Mac, where wx has no API for it."""
    if sys.platform != "darwin":
        return
    try:
        ctypes, objc, send, nsstr = _objc()
        view = ctrl.GetHandle()
        targets = [view]
        if send(view, "respondsToSelector:", objc.sel_registerName(b"documentView"),
                restype=ctypes.c_bool, argtypes=(ctypes.c_void_p,)):
            doc = send(view, "documentView")
            if doc:
                targets.append(doc)
        for t in targets:
            send(t, "setAccessibilityLabel:", nsstr(text), restype=None, argtypes=(ctypes.c_void_p,))
    except Exception:  # noqa: BLE001 - a missing label must never stop the app
        pass


def announce(text: str, polite: bool = False) -> None:
    if not text:
        return
    if sys.platform == "win32":
        _announce_windows(text, polite)
        return
    if sys.platform != "darwin":
        return
    try:
        ctypes, objc, send, nsstr = _objc()
        appkit = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/AppKit.framework/AppKit")
        info = send(objc.objc_getClass(b"NSMutableDictionary"), "dictionary")
        send(info, "setObject:forKey:", nsstr(text), nsstr("AXAnnouncementKey"),
             restype=None, argtypes=(ctypes.c_void_p, ctypes.c_void_p))
        pri = send(objc.objc_getClass(b"NSNumber"), "numberWithInt:", 50 if polite else 90, argtypes=(ctypes.c_int,))
        send(info, "setObject:forKey:", pri, nsstr("AXPriorityKey"),
             restype=None, argtypes=(ctypes.c_void_p, ctypes.c_void_p))
        app = send(objc.objc_getClass(b"NSApplication"), "sharedApplication")
        post = appkit.NSAccessibilityPostNotificationWithUserInfo
        post.restype = None
        post.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        post(app, nsstr("AXAnnouncementRequested"), info)
    except Exception:  # noqa: BLE001
        pass


# Windows, from Wavelength: the running screen reader through Prism, else UI Automation
# notifications (Narrator hears those). Never SAPI: with no screen reader running, a sighted
# person shouldn't suddenly be talked at.
_win_reader = {"ctx": None, "failed": False}
_WIN_ORDER = ("NVDA", "JAWS", "ZDSR", "SYSTEM_ACCESS", "ZOOM_TEXT", "SENSE_READER", "PC_TALKER",
              "BOY_PC_READER", "UIA")


def load_prism():
    """Import Prism, also inside the packaged app, where its compiled part must be found by
    name and loaded first (the packaged importer doesn't follow prism/_native)."""
    import os
    if getattr(sys, "frozen", False) and "prism._prism_cffi" not in sys.modules:
        import importlib.util
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        for root, _, files in os.walk(base):
            hit = [f for f in files if f.startswith("_prism_cffi") and f.endswith((".pyd", ".so"))]
            if hit:
                if sys.platform == "win32":
                    os.add_dll_directory(root)
                spec = importlib.util.spec_from_file_location("prism._prism_cffi", os.path.join(root, hit[0]))
                mod = importlib.util.module_from_spec(spec)
                sys.modules["prism._prism_cffi"] = mod
                spec.loader.exec_module(mod)
                break
    import prism
    return prism


def _announce_windows(text: str, polite: bool = False) -> str | None:
    if _win_reader["failed"]:
        return None
    try:
        prism = load_prism()
        if _win_reader["ctx"] is None:
            _win_reader["ctx"] = prism.Context()
        ctx = _win_reader["ctx"]
        for name in _WIN_ORDER:
            bid = getattr(prism.BackendId, name, None)
            if bid is None or not ctx.exists(bid):
                continue
            try:
                backend = ctx.acquire(bid)
            except Exception:  # noqa: BLE001 - that reader isn't running
                continue
            feats = backend.features
            if name != "UIA" and not feats.is_supported_at_runtime:
                continue
            try:
                if feats.supports_output:
                    backend.output(text, interrupt=not polite)   # speech and braille
                else:
                    backend.speak(text, interrupt=not polite)
            except Exception:  # noqa: BLE001 - a reader hiccuped: try the next
                continue
            return name
    except Exception:  # noqa: BLE001 - no Prism: the status line still shows it
        _win_reader["failed"] = True
    return None


def voiceover_on() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        ctypes, objc, send, nsstr = _objc()
        ws = send(objc.objc_getClass(b"NSWorkspace"), "sharedWorkspace")
        return bool(send(ws, "isVoiceOverEnabled", restype=ctypes.c_bool))
    except Exception:  # noqa: BLE001
        return False


_check_imps: list = []      # ctypes callbacks must outlive the Objective-C methods using them
_check_tables: dict = {}
_check_classes: set = set()


def _objc_send():
    ctypes, _objc_lib, send, _nsstr = _objc()
    return ctypes, send


def mac_check_list_reads_once(ctrl) -> None:
    """Make VoiceOver read a wx.CheckListBox row once (Matthew, 2026-10-14).

    Each row is a checkbox with no name and the row's text beside it. VoiceOver names the
    checkbox after that text, then reads the text again on its own: "2. So What, unchecked
    checkbox, 2. So What". Here the checkbox is named with the row's text as each row is
    prepared, and the text cell answers VoiceOver with nothing, so the row reads "2. So What,
    unchecked checkbox", once. What's drawn is unchanged. A failure leaves the list as it was."""
    if sys.platform != "darwin":
        return
    try:
        ctypes, send = _objc_send()
        import ctypes.util
        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        for fn, res, args in (("object_getClass", ctypes.c_void_p, [ctypes.c_void_p]),
                              ("object_setClass", ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_void_p]),
                              ("objc_getClass", ctypes.c_void_p, [ctypes.c_char_p]),
                              ("objc_allocateClassPair", ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]),
                              ("objc_registerClassPair", None, [ctypes.c_void_p]),
                              ("class_getMethodImplementation", ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_void_p]),
                              ("class_addMethod", ctypes.c_bool,
                               [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p]),
                              ("sel_registerName", ctypes.c_void_p, [ctypes.c_char_p])):
            getattr(objc, fn).restype = res
            getattr(objc, fn).argtypes = args
        sel = objc.sel_registerName
        table = send(ctrl.GetHandle(), "documentView")
        cols = send(table, "tableColumns")
        if not table or send(cols, "count", restype=ctypes.c_ulong) != 2:
            return
        check_col = send(cols, "objectAtIndex:", 0, argtypes=(ctypes.c_ulong,))
        text_col = send(cols, "objectAtIndex:", 1, argtypes=(ctypes.c_ulong,))

        # The text cell: a subclass of its own class whose value VoiceOver hears as nothing.
        quiet = objc.objc_getClass(b"RPLMakerQuietTextCell")
        if not quiet:
            base = objc.objc_getClass(b"NSTextFieldCell")
            quiet = objc.objc_allocateClassPair(base, b"RPLMakerQuietTextCell", 0)
            empty = send(objc.objc_getClass(b"NSString"), "string")
            send(empty, "retain")
            VAL = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
            ATTR = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
            sup_attr = ATTR(objc.class_getMethodImplementation(base, sel(b"accessibilityAttributeValue:")))
            ax_value = send(objc.objc_getClass(b"NSString"), "stringWithUTF8String:", b"AXValue",
                            argtypes=(ctypes.c_char_p,))
            send(ax_value, "retain")

            def attr_imp(self_, _cmd, name):
                if name and send(name, "isEqualToString:", ax_value, restype=ctypes.c_bool,
                                 argtypes=(ctypes.c_void_p,)):
                    return empty
                return sup_attr(self_, _cmd, name)
            value = VAL(lambda self_, _cmd: empty)
            attr = ATTR(attr_imp)
            _check_imps.extend([value, attr, sup_attr])
            objc.class_addMethod(quiet, sel(b"accessibilityValue"), ctypes.cast(value, ctypes.c_void_p), b"@@:")
            objc.class_addMethod(quiet, sel(b"accessibilityAttributeValue:"), ctypes.cast(attr, ctypes.c_void_p), b"@@:@")
            objc.objc_registerClassPair(quiet)
        cell = send(text_col, "dataCell")
        if send(cell, "isMemberOfClass:", objc.objc_getClass(b"NSTextFieldCell"), restype=ctypes.c_bool,
                argtypes=(ctypes.c_void_p,)):
            objc.object_setClass(cell, quiet)  # adds no instance variables, so this is safe

        # The checkbox: named with its row's text as AppKit prepares each row, for drawing and
        # for VoiceOver alike. The table is its own delegate in wx.
        _check_tables[table] = (check_col, text_col)

        def forget(event):
            if event.GetEventObject() is ctrl:
                _check_tables.pop(table, None)  # a later table could be given this address
            event.Skip()
        import wx
        ctrl.Bind(wx.EVT_WINDOW_DESTROY, forget)
        cls = objc.object_getClass(table)
        if cls not in _check_classes:
            _check_classes.add(cls)
            WILL = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_void_p, ctypes.c_long)

            def will_imp(self_, _cmd, tv, c, col, row):
                pair = _check_tables.get(tv)
                if not pair or col != pair[0]:
                    return
                text = send(send(tv, "dataSource"), "tableView:objectValueForTableColumn:row:", tv, pair[1], row,
                            argtypes=(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long))
                if text:
                    send(c, "setAccessibilityLabel:", text, restype=None, argtypes=(ctypes.c_void_p,))
            will = WILL(will_imp)
            _check_imps.append(will)
            objc.class_addMethod(cls, sel(b"tableView:willDisplayCell:forTableColumn:row:"),
                                 ctypes.cast(will, ctypes.c_void_p), b"v@:@@@q")
        # AppKit asks a delegate what it can do when it's set, so set it again to be asked anew.
        delegate = send(table, "delegate")
        send(table, "setDelegate:", None, restype=None, argtypes=(ctypes.c_void_p,))
        send(table, "setDelegate:", delegate, restype=None, argtypes=(ctypes.c_void_p,))
        send(table, "reloadData", restype=None)
    except Exception:  # noqa: BLE001 - never stop the app over this
        pass




def mac_escape_presses(title: str, window=None) -> bool:
    """Make Escape press the button called `title` in the open alert (Matthew's rule: Escape
    always means the way out). macOS gives Escape only to a button called "Cancel", so an
    alert with "Not Now" would otherwise have no Escape at all. Call it with wx.CallLater
    just before ShowModal: wx's timers run inside the alert's modal loop. True when done."""
    if sys.platform != "darwin":
        return False
    try:
        ctypes, objc, send, nsstr = _objc()
        if window is None:
            app = send(objc.objc_getClass(b"NSApplication"), "sharedApplication")
            window = send(app, "modalWindow") or send(app, "keyWindow")
        if not window:
            return False
        want = nsstr(title)
        button_cls = objc.objc_getClass(b"NSButton")
        stack = [send(window, "contentView")]
        while stack:
            view = stack.pop()
            if not view:
                continue
            if send(view, "isKindOfClass:", button_cls, restype=ctypes.c_bool, argtypes=(ctypes.c_void_p,)) and \
                    send(send(view, "title"), "isEqualToString:", want, restype=ctypes.c_bool,
                         argtypes=(ctypes.c_void_p,)):
                send(view, "setKeyEquivalent:", nsstr("\x1b"), restype=None, argtypes=(ctypes.c_void_p,))
                return True
            subs = send(view, "subviews")
            for i in range(send(subs, "count", restype=ctypes.c_ulong)):
                stack.append(send(subs, "objectAtIndex:", i, argtypes=(ctypes.c_ulong,)))
    except Exception:  # noqa: BLE001 - never stop the app over this
        pass
    return False
