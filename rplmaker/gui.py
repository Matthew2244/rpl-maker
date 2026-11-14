"""The window. One list of plug-ins, check the ones you want, make their libraries.

House rules (from Wavelength): native controls; every control has a spoken name and a help
tag; rows say their status first; nothing talks on a timer; finishes and failures are
spoken, politely unless someone is waiting on them; every shortcut means one thing;
everything works from the keyboard. Controls are made in reading order, label first,
because VoiceOver reads a Mac window in the order its controls were created.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

import wx

from . import APP_NAME, VERSION, formats, inventory, pipeline, portable, settings, speech, updates

CMD = "Command" if sys.platform == "darwin" else "Control"


class StopRequested(Exception):
    pass


def say(text: str, polite: bool = True) -> None:
    speech.announce(text, polite)


def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def row_words(p: inventory.Plugin, result: pipeline.Result | None) -> str:
    """A row: status first once something has happened to it, else what it has."""
    if result is not None:
        return result.sentence()
    fmt, found = p.best()
    if not found:
        return f"{p.name}, {p.vendor}: no preset files found"
    return (f"{p.name}, {p.vendor}: {len(found)} {formats.SHORT_WORDS[fmt]} preset{'' if len(found) == 1 else 's'}"
            + ("" if formats.exact_copies(fmt, found) else ", worth a try"))


def details_words(p: inventory.Plugin, result: pipeline.Result | None) -> str:
    L = [f"{p.name}", f"Made by {p.vendor or 'an unknown maker'}. REAPER calls it {p.fx}."]
    fmt, found = p.best()
    if found:
        folders = sorted({os.path.dirname(f.path) for f in found})
        L.append(f"{plural(len(found), 'preset file')} found, {formats.FORMAT_WORDS[fmt]}, "
                 f"in {plural(len(folders), 'folder')}:")
        L += ["  " + d for d in folders[:6]]
        if len(folders) > 6:
            L.append(f"  and {len(folders) - 6} more")
        others = {k: len(v) for k, v in p.presets.items() if k != fmt and v}
        for k, n in others.items():
            L.append(f"There are also {n} {formats.SHORT_WORDS[k]} presets; the {formats.SHORT_WORDS[fmt]} ones are used instead.")
        if len(found) > 2000:
            L.append(f"That many takes a long time to check. A run can be stopped at any point, and the "
                     f"libraries made by then are kept.")
        if formats.exact_copies(fmt, found):
            L.append("These hold the plug-in's own settings exactly, so they usually all work.")
        else:
            L.append("These are in a form some plug-ins accept and some don't. Checking them is the only way to know.")
    else:
        L.append("No preset files this can read were found for it.")
    if result is not None:
        L.append("")
        L.append(result.sentence())
        for path, n in result.files:
            L.append(f"Saved as {os.path.basename(path)}, {plural(n, 'preset')}, in {os.path.dirname(path)}")
        for label, n in result.small:
            L.append(f"The {label} folder wasn't saved: only {n} working, fewer than a library needs.")
        L += pipeline.reason_lines(result.cut)
        for path, why in result.unreadable[:8]:
            L.append(f"Couldn't read {os.path.basename(path)}: {why}.")
    return "\n".join(L)


def open_path(path: str, text: bool = False) -> None:
    """Show a folder, or open a report in the text editor (TextEdit; Notepad on Windows)."""
    if sys.platform == "win32":
        if text:
            subprocess.Popen(["notepad.exe", path])
        else:
            os.startfile(path)   # noqa: S606 - a folder the person chose
    else:
        subprocess.run(["open", "-e", path] if text else ["open", path])


def make_label(parent, text):
    return wx.StaticText(parent, label=text)


class MainFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title=APP_NAME, size=(900, 680))
        self.cfg = settings.load()
        self.plugs: list[inventory.Plugin] = []
        self.shown: list[inventory.Plugin] = []
        self.results: dict[str, pipeline.Result] = {}
        self.busy = None            # "scan" or "build"
        self.stop_flag = False
        self.progress_words = "Nothing is happening yet."
        self.last_report = None
        self.builder = None
        self.scanned_once = False

        panel = wx.Panel(self)
        s = wx.BoxSizer(wx.VERTICAL)

        # 1. find and show, label before control
        row = wx.BoxSizer(wx.HORIZONTAL)
        fl = make_label(panel, "Find:")
        self.find = wx.SearchCtrl(panel, size=(320, -1))
        self.find.ShowCancelButton(True)
        col = wx.BoxSizer(wx.VERTICAL)
        col.Add(fl, 0, wx.BOTTOM, 3)
        col.Add(self.find, 0)
        row.Add(col, 0, wx.ALL, 6)
        speech.label(self.find, "Find")
        self.find.SetToolTip("Type part of a plug-in's or maker's name to show only those. "
                             f"{CMD}-F comes here from anywhere in the window.")
        sl = make_label(panel, "Show:")
        self.show = wx.Choice(panel, choices=["Plug-ins with presets", "Every plug-in", "Checked plug-ins",
                                              "Made, or tried, this time"])
        self.show.SetSelection(0)
        col = wx.BoxSizer(wx.VERTICAL)
        col.Add(sl, 0, wx.BOTTOM, 3)
        col.Add(self.show, 0)
        row.Add(col, 0, wx.ALL, 6)
        speech.label(self.show, "Show")
        self.show.SetToolTip("Which plug-ins the list shows. Plug-ins with presets: only those with preset "
                             "files this can read. Every plug-in: all your VST3 plug-ins. Checked: the ones "
                             "you've checked. Made, or tried: what happened this time.")
        s.Add(row, 0)

        # 2. the list
        ll = make_label(panel, "Plug-ins:")
        s.Add(ll, 0, wx.LEFT | wx.TOP, 6)
        self.list = wx.CheckListBox(panel, choices=[])
        speech.mac_check_list_reads_once(self.list)
        speech.label(self.list, "Plug-ins")
        self.list.SetToolTip("Space checks or unchecks the selected plug-in. Make Libraries makes a library for "
                             "every checked one. The details below say what was found for the selected one.")
        s.Add(self.list, 3, wx.EXPAND | wx.ALL, 6)
        self.count = wx.StaticText(panel, label="")
        s.Add(self.count, 0, wx.LEFT, 8)

        # 3. details, right after the list: select, Tab, read
        dl = make_label(panel, "Details:")
        s.Add(dl, 0, wx.LEFT | wx.TOP, 6)
        self.details = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        speech.label(self.details, "Details")
        self.details.SetToolTip("What was found for the selected plug-in, and what happened when it was made.")
        self.details.SetValue("Looking for your plug-ins and their presets.")
        s.Add(self.details, 2, wx.EXPAND | wx.ALL, 6)

        # 4. buttons
        brow = wx.BoxSizer(wx.HORIZONTAL)
        self.b_make = wx.Button(panel, label="Make Libraries")
        self.b_make.SetToolTip(f"Makes a library for every checked plug-in and checks each preset in a separate "
                               f"copy of REAPER ({CMD}-B). Your own REAPER and its presets aren't touched.")
        self.b_stop = wx.Button(panel, label="Stop")
        self.b_stop.SetToolTip(f"Stops now ({CMD}-period). Libraries already made are kept; the plug-in being "
                               "checked is left unfinished, and the report says which were never started.")
        self.b_all = wx.Button(panel, label="Check All Shown")
        self.b_all.SetToolTip("Checks every plug-in the list is showing now.")
        self.b_none = wx.Button(panel, label="Uncheck All")
        self.b_none.SetToolTip("Unchecks every plug-in, shown or not.")
        self.b_folder = wx.Button(panel, label="Show Libraries in " + ("File Explorer" if sys.platform == "win32" else "Finder"))
        self.b_folder.SetToolTip("Opens the folder the libraries are saved in.")
        self.b_report = wx.Button(panel, label="Open Report")
        self.b_report.SetToolTip("Opens the report of the last run in " +
                                 ("Notepad" if sys.platform == "win32" else "TextEdit") +
                                 ": what was made, what was left out and why, and how to import a library.")
        for b in (self.b_make, self.b_stop, self.b_all, self.b_none, self.b_folder, self.b_report):
            brow.Add(b, 0, wx.ALL, 4)
        s.Add(brow, 0, wx.LEFT, 2)

        # 5. progress
        self.status = wx.StaticText(panel, label="Looking for your plug-ins and their presets.")
        s.Add(self.status, 0, wx.ALL | wx.EXPAND, 8)
        self.gauge = wx.Gauge(panel, range=100)
        speech.label(self.gauge, "Progress")
        self.gauge.SetToolTip(f"How far the current job has got. {CMD}-P says what's happening now.")
        s.Add(self.gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        panel.SetSizer(s)

        self._menus()
        self.find.Bind(wx.EVT_TEXT, lambda e: self.refill())
        self.show.Bind(wx.EVT_CHOICE, lambda e: self.refill())
        self.list.Bind(wx.EVT_LISTBOX, lambda e: self.show_details())
        self.list.Bind(wx.EVT_CHECKLISTBOX, self.on_check)
        self.b_make.Bind(wx.EVT_BUTTON, lambda e: self.on_make())
        self.b_stop.Bind(wx.EVT_BUTTON, lambda e: self.on_stop())
        self.b_all.Bind(wx.EVT_BUTTON, lambda e: self.set_all(True))
        self.b_none.Bind(wx.EVT_BUTTON, lambda e: self.set_all(False))
        self.b_folder.Bind(wx.EVT_BUTTON, lambda e: self.on_folder())
        self.b_report.Bind(wx.EVT_BUTTON, lambda e: self.on_report())
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.checked: set[str] = set(self.cfg.get("checked", []))
        self._enable()
        self.Centre()
        wx.CallAfter(self.scan)
        wx.CallAfter(self._start_updates)

    # -- updates: heard, never popped up --------------------------------------------------
    def _start_updates(self):
        updates.start(on_shutdown=lambda: wx.CallAfter(self.Close))
        self.update_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda e: self._look_for_update(), self.update_timer)
        self.update_timer.StartOnce(15_000)   # then every 4 hours, below

    def _look_for_update(self):
        if not self:
            return
        self.update_timer.Start(4 * 3600 * 1000)

        def work():
            v = updates.newest()
            if updates.is_newer(v):
                wx.CallAfter(self._tell_update, v)
        threading.Thread(target=work, daemon=True).start()

    def _tell_update(self, v):
        """Once per version, politely, only with this window in front and nothing open over it;
        otherwise the next look (4 hours) tries again."""
        if not self or settings.load().get("told_update") == v:
            return
        if not wx.GetApp().IsActive() or wx.GetActiveWindow() is not self:
            return
        settings.save({"told_update": v})
        say(f"{APP_NAME} {v} is out. Help, Check for Updates shows what's new and installs it.", polite=True)

    def on_updates(self):
        if not updates.check_with_window():
            import webbrowser
            say("Opening the releases page in your browser.", polite=False)
            webbrowser.open(updates.REPO + "/releases")

    # -- menus: every shortcut means one thing ----------------------------------------------
    def _menus(self):
        mb = wx.MenuBar()
        m = wx.Menu()
        self.mi_make = m.Append(wx.ID_ANY, "Make Libraries\tCtrl+B", "Make libraries for the checked plug-ins")
        self.mi_stop = m.Append(wx.ID_ANY, "Stop\tCtrl+.", "Stop now; libraries already made are kept")
        m.AppendSeparator()
        mi_scan = m.Append(wx.ID_ANY, "Look for Presets Again\tCtrl+R", "Look for plug-ins and presets again")
        self.mi_access = (m.Append(wx.ID_ANY, "Allow Folder Access...",
                                   "Let macOS ask now whether the checking copy may open your folders")
                          if sys.platform == "darwin" else None)   # Windows never asks
        mi_folder = m.Append(wx.ID_ANY, "Show Libraries in " + ("File Explorer" if sys.platform == "win32" else "Finder")
                             + "\tCtrl+Shift+F", "Open the libraries folder")
        mi_report = m.Append(wx.ID_ANY, "Open Report\tCtrl+Shift+R", "Open the last run's report")
        m.AppendSeparator()
        mi_set = m.Append(wx.ID_PREFERENCES, "Settings...\tCtrl+,", "Settings")
        mi_quit = m.Append(wx.ID_EXIT, "Quit\tCtrl+Q", "Quit")
        mb.Append(m, "&File")
        e = wx.Menu()
        mi_all = e.Append(wx.ID_ANY, "Check All Shown\tCtrl+Shift+A", "Check every plug-in shown")
        mi_none = e.Append(wx.ID_ANY, "Uncheck All\tCtrl+Shift+U", "Uncheck every plug-in")
        mb.Append(e, "&Edit")
        v = wx.Menu()
        mi_find = v.Append(wx.ID_ANY, "Find\tCtrl+F", "Go to the Find field")
        mi_list = v.Append(wx.ID_ANY, "Go to the List\tCtrl+L", "Go to the plug-in list")
        mi_prog = v.Append(wx.ID_ANY, "Say Progress\tCtrl+P", "Say what's happening now")
        mb.Append(v, "&View")
        h = wx.Menu()
        mi_imp = h.Append(wx.ID_ANY, "How to Import a Library", "How to use a library in REAPER")
        mi_how = h.Append(wx.ID_ANY, "How Presets Are Checked", "What makes a preset pass")
        h.AppendSeparator()
        mi_upd = h.Append(wx.ID_ANY, "Check for Updates...\tCtrl+U", "See whether a newer version is out")
        mi_about = h.Append(wx.ID_ABOUT, f"About {APP_NAME}", "About")
        mb.Append(h, "&Help")
        self.SetMenuBar(mb)
        B = self.Bind
        B(wx.EVT_MENU, lambda e: self.on_make(), self.mi_make)
        B(wx.EVT_MENU, lambda e: self.on_stop(), self.mi_stop)
        B(wx.EVT_MENU, lambda e: self.scan(), mi_scan)
        if self.mi_access:
            B(wx.EVT_MENU, lambda e: self.on_access(), self.mi_access)
        B(wx.EVT_MENU, lambda e: self.on_folder(), mi_folder)
        B(wx.EVT_MENU, lambda e: self.on_report(), mi_report)
        B(wx.EVT_MENU, lambda e: self.on_settings(), mi_set)
        B(wx.EVT_MENU, lambda e: self.Close(), mi_quit)
        B(wx.EVT_MENU, lambda e: self.set_all(True), mi_all)
        B(wx.EVT_MENU, lambda e: self.set_all(False), mi_none)
        B(wx.EVT_MENU, lambda e: self.find.SetFocus(), mi_find)
        B(wx.EVT_MENU, lambda e: self.list.SetFocus(), mi_list)
        B(wx.EVT_MENU, lambda e: say(self.progress_words, polite=False), mi_prog)
        B(wx.EVT_MENU, lambda e: self.message("How to Import a Library", pipeline.IMPORT_STEPS), mi_imp)
        B(wx.EVT_MENU, lambda e: self.message("How Presets Are Checked", HOW_CHECKED), mi_how)
        B(wx.EVT_MENU, lambda e: self.message(f"About {APP_NAME}", ABOUT), mi_about)
        B(wx.EVT_MENU, lambda e: self.on_updates(), mi_upd)

    def message(self, title, text):
        dlg = wx.MessageDialog(self, text, title, wx.OK)
        dlg.ShowModal()
        dlg.Destroy()

    # -- state -------------------------------------------------------------------------------
    def set_progress(self, words: str, frac: float | None = None):
        if not self:   # the window was closed while work finished in the background
            return
        self.progress_words = words
        self.status.SetLabel(words)
        if frac is not None:
            self.gauge.SetValue(max(0, min(100, int(frac * 100))))

    def _enable(self):
        idle = self.busy is None
        self.b_make.Enable(idle and bool(self.checked))
        self.mi_make.Enable(idle)
        if self.mi_access:
            self.mi_access.Enable(idle)
        self.b_stop.Enable(self.busy == "build")
        self.mi_stop.Enable(self.busy == "build")
        self.b_report.Enable(bool(self.last_report))

    def refill(self):
        want = inventory.norm(self.find.GetValue())
        mode = self.show.GetSelection()
        keep_sel = None
        sel = self.list.GetSelection()
        if sel != wx.NOT_FOUND and sel < len(self.shown):
            keep_sel = self.shown[sel].class_id
        out = []
        for p in self.plugs:
            if want and want not in inventory.norm(p.name + p.vendor):
                continue
            if mode == 0 and not p.count:
                continue
            if mode == 2 and p.class_id not in self.checked:
                continue
            if mode == 3 and p.class_id not in self.results:
                continue
            out.append(p)
        self.shown = out
        self.list.Set([row_words(p, self.results.get(p.class_id)) for p in out])
        for i, p in enumerate(out):
            if p.class_id in self.checked:
                self.list.Check(i)
        if keep_sel:
            for i, p in enumerate(out):
                if p.class_id == keep_sel:
                    self.list.SetSelection(i)
                    break
        elif out:
            self.list.SetSelection(0)
        self.count_words()
        self.show_details()

    def count_words(self):
        n = len(self.checked)
        total = sum(p.count for p in self.plugs if p.class_id in self.checked)
        self.count.SetLabel(f"Showing {plural(len(self.shown), 'plug-in')}. "
                            + (f"{n} checked, {plural(total, 'preset')} to check." if n else "None checked."))
        self._enable()

    def show_details(self):
        i = self.list.GetSelection()
        if not self.shown:
            if self.busy == "scan":
                self.details.SetValue("Still looking for your plug-ins and their presets.")
            elif self.find.GetValue().strip():
                self.details.SetValue(f"No plug-in shown here matches {self.find.GetValue().strip()!r}. "
                                      "Clear Find, or choose Every plug-in under Show.")
            elif self.plugs:
                self.details.SetValue("Nothing to show with this choice under Show.")
            else:
                self.details.SetValue(self.progress_words)
            return
        if i == wx.NOT_FOUND or i >= len(self.shown):
            self.details.SetValue("Select a plug-in to read what was found for it.")
            return
        p = self.shown[i]
        self.details.SetValue(details_words(p, self.results.get(p.class_id)))

    def on_check(self, e):
        i = e.GetInt()
        p = self.shown[i]
        if self.list.IsChecked(i):
            self.checked.add(p.class_id)
        else:
            self.checked.discard(p.class_id)
        self.count_words()
        # VoiceOver can read the row before the check lands; say the new count instead
        say(self.count.GetLabel(), polite=True)

    def set_all(self, on: bool):
        if on:
            for i, p in enumerate(self.shown):
                if p.count:
                    self.checked.add(p.class_id)
                    self.list.Check(i)
        else:
            self.checked.clear()
            for i in range(len(self.shown)):
                self.list.Check(i, False)
        self.count_words()
        say(self.count.GetLabel(), polite=False)

    # -- scanning ----------------------------------------------------------------------------
    def scan(self):
        if self.busy:
            return
        self.busy = "scan"
        self._enable()
        self.set_progress("Looking for your plug-ins and their presets.", 0)
        folders = list(self.cfg.get("extra_folders", []))

        def progress(stage, a, b):
            if stage == "reading" and b:
                wx.CallAfter(self.set_progress, f"Reading preset files: {a} of {b}.", a / b)

        def work():
            try:
                plugs = inventory.scan(folders, progress=progress)
                err = None
            except Exception as ex:  # noqa: BLE001
                plugs, err = [], str(ex)
            wx.CallAfter(self.scan_done, plugs, err)
        threading.Thread(target=work, daemon=True).start()

    def scan_done(self, plugs, err):
        if not self:   # the window was closed while work finished in the background
            return
        self.busy = None
        self.plugs = plugs
        known = {p.class_id for p in plugs}
        self.checked &= known
        with_presets = sum(1 for p in plugs if p.count)
        first = not self.scanned_once
        self.scanned_once = True
        if err:
            words = "Couldn't look for presets: " + err
        elif not plugs and portable.find_reaper() is None:
            words = ("REAPER isn't installed on this Mac. This app makes presets for REAPER and checks them in "
                     "a copy of it, so install REAPER, open it once so it finds your plug-ins, then Look for "
                     "Presets Again.")
        elif not plugs:
            words = ("No VST3 plug-ins found. This reads REAPER's own list of your plug-ins, so open REAPER once "
                     "so it can scan them, then Look for Presets Again.")
        elif not with_presets:
            words = (f"None of your {plural(len(plugs), 'VST3 plug-in')} has preset files this can read in the "
                     "usual places. If a maker keeps presets somewhere else, add that folder in Settings.")
        else:
            words = (f"Found {plural(with_presets, 'plug-in')} with presets this can read, "
                     f"of {plural(len(plugs), 'VST3 plug-in')}.")
        self.set_progress(words, 1)
        self.refill()
        if first and self.shown and wx.Window.FindFocus() in (None, self.find):
            self.list.SetFocus()   # the first thing worth reaching is the list, not an empty Find field
        say(words, polite=True)

    # -- making ------------------------------------------------------------------------------
    def on_make(self):
        if self.busy:
            return
        chosen = [p for p in self.plugs if p.class_id in self.checked and p.count]
        if not chosen:
            say("Nothing is checked. Check the plug-ins you want, with Space, then Make Libraries.", polite=False)
            self.list.SetFocus()
            return
        st = portable.status()
        if st == "missing":
            self.message("REAPER Isn't Installed", "REAPER isn't installed on this Mac, so there's nothing to "
                         "check presets with. Install REAPER, then try again.")
            return
        presets_total = sum(p.count for p in chosen)
        if presets_total > 5000:
            dlg = wx.MessageDialog(self, f"That's {presets_total:,} presets to load one by one, which can take "
                                   "hours. You can stop at any point, and libraries already made are kept. "
                                   "Start anyway?", "A Big Run", wx.OK | wx.CANCEL)
            dlg.SetOKCancelLabels("Start", "Cancel")
            go = dlg.ShowModal() == wx.ID_OK
            dlg.Destroy()
            if not go:
                return
        self.busy = "build"
        self.stop_flag = False
        self._enable()
        self.cfg["checked"] = sorted(self.checked)
        settings.save({"checked": self.cfg["checked"]})
        total = sum(p.count + 1 for p in chosen)
        done_before = [0]
        current = [""]
        told_waiting = [False]
        n_plugs = len(chosen)
        out = os.path.expanduser(self.cfg["out_dir"])
        say(f"Making {plural(n_plugs, 'library', 'libraries')}, {plural(total - n_plugs, 'preset')} to check.",
            polite=False)

        def events(kind, *a):
            if kind == "plugin":
                p, i, n = a
                current[0] = p.name
                wx.CallAfter(self.set_progress, f"{i} of {n}: {p.name}. Loading it.", done_before[0] / total)
            elif kind == "phase":
                p, words = a
                wx.CallAfter(self.set_progress, f"{p.name}: {words}.", None)
            elif kind == "preset":
                label, k, n = a
                wx.CallAfter(self.set_progress, f"{current[0]}: {label.lower()} {k} of {n} presets.",
                             min(1.0, (done_before[0] + (k if label == 'Checking' else n)) / total))
            elif kind == "waiting":
                p, words = a
                if not told_waiting[0]:      # once a run: the same advice twice is noise
                    told_waiting[0] = True
                    wx.CallAfter(say, words, False)
                wx.CallAfter(self.set_progress, f"{p.name}: waiting. " + words, None)
            elif kind == "result":
                r = a[0]
                done_before[0] += r.plugin.count + 1
                wx.CallAfter(self.one_done, r)

        self.builder = pipeline.Builder(out, author=self.cfg["author"], min_keep=int(self.cfg["min_keep"]),
                                        check_twice=bool(self.cfg["check_twice"]),
                                        split_over=int(self.cfg["split_over"]) if self.cfg["split_big"] else 0,
                                        events=events, stop=lambda: self.stop_flag)

        def work():
            err = None
            results = []
            try:
                if st in ("none", "stale"):
                    wx.CallAfter(self.set_progress, "Making the checking copy of REAPER, once.", 0)
                    portable.make()
                if self.stop_flag:
                    raise StopRequested
                results = self.builder.build(chosen)
            except StopRequested:
                pass
            except Exception as ex:  # noqa: BLE001
                err = str(ex)
            report = pipeline.write_report(results, out) if results else None
            wx.CallAfter(self.build_done, results, report, err)
        threading.Thread(target=work, daemon=True).start()

    def one_done(self, r: pipeline.Result, speak: bool = True):
        if not self:   # the window was closed while work finished in the background
            return
        self.results[r.plugin.class_id] = r
        for i, p in enumerate(self.shown):
            if p is r.plugin:
                self.list.SetString(i, row_words(p, r))
                if p.class_id in self.checked:
                    self.list.Check(i)
        self.show_details()
        if speak and self.cfg.get("speak", True):
            say(r.sentence(), polite=r.status == "made")

    def build_done(self, results, report, err):
        if not self:   # the window was closed while work finished in the background
            return
        self.busy = None
        self.builder = None
        if report:
            self.last_report = report
        for r in results:   # stopped and never-started ones have no result event of their own
            if r.status in ("stopped", "skipped"):
                self.one_done(r, speak=False)
        made = [r for r in results if r.status == "made"]
        presets = sum(len(r.kept) for r in made)
        files = sum(len(r.files) for r in made)
        tally = (f"{plural(files, 'library', 'libraries')} made for {len(made)} of {plural(len(results), 'plug-in')}, "
                 f"{plural(presets, 'working preset')}")
        if err:
            words = "Couldn't make libraries: " + err
        elif self.stop_flag:
            words = f"Stopped. {tally}." + (" Open Report has the details." if report else "")
        else:
            words = f"Done. {tally}. Open Report has the details."
        self.set_progress(words, 1)
        self._enable()
        say(words, polite=False)

    def on_access(self):
        if self.busy:
            return
        folders = portable.protected_folders()
        dlg = wx.MessageDialog(self, ACCESS_WORDS + "\n\nPlaces: " + ", ".join(os.path.basename(f) or f for f in folders),
                               "Allow Folder Access", wx.OK | wx.CANCEL)
        dlg.SetOKCancelLabels("Start", "Cancel")
        go = dlg.ShowModal() == wx.ID_OK
        dlg.Destroy()
        if not go:
            return
        self.busy = "access"
        self._enable()

        def work():
            try:
                if portable.status() != "ready":
                    portable.make()
                res = pipeline.allow_folders(events=lambda k, d: wx.CallAfter(
                    self.set_progress, f"Opening {d}. If macOS asks, choose Allow.", None))
                ok = sum(1 for _d, o in res if o)
                words = f"Done. The checking copy opened {ok} of {plural(len(res), 'place')}."
            except Exception as ex:  # noqa: BLE001
                words = "Couldn't finish: " + str(ex)
            wx.CallAfter(self.access_done, words)
        threading.Thread(target=work, daemon=True).start()

    def access_done(self, words):
        if not self:   # the window was closed while work finished in the background
            return
        self.busy = None
        self._enable()
        self.set_progress(words, 1)
        say(words, polite=False)

    def on_stop(self):
        if self.busy == "build" and not self.stop_flag:
            self.stop_flag = True
            if self.builder:
                self.builder.abort()   # ends the checking copy now; libraries already made stay
            self.set_progress("Stopping.")
            say("Stopping.", polite=False)

    def on_folder(self):
        out = os.path.expanduser(self.cfg["out_dir"])
        os.makedirs(out, exist_ok=True)
        open_path(out)

    def on_report(self):
        if self.last_report and os.path.exists(self.last_report):
            open_path(self.last_report, text=True)
        elif self.last_report:
            say("The report isn't there any more; it may have been moved or deleted.", polite=False)

    def on_settings(self):
        dlg = SettingsDialog(self, self.cfg)
        if dlg.ShowModal() == wx.ID_OK:
            old_folders = list(self.cfg.get("extra_folders", []))
            self.cfg.update(dlg.values())
            settings.save(self.cfg)
            if self.cfg["extra_folders"] != old_folders and not self.busy:
                wx.CallAfter(self.scan)
        dlg.Destroy()

    def on_close(self, e):
        if self.busy == "build":
            dlg = wx.MessageDialog(self, "Libraries are being made. Quit anyway? The one being checked now "
                                   "won't be finished; those already made are kept.", "Quit While Making?",
                                   wx.YES_NO | wx.NO_DEFAULT)
            dlg.SetYesNoLabels("Quit Anyway", "Cancel")
            ok = dlg.ShowModal() == wx.ID_YES
            dlg.Destroy()
            if not ok:
                e.Veto()
                return
            self.stop_flag = True
            if self.builder:
                self.builder.abort()   # ends the checking copy for good; the run's thread can't restart it
        settings.save({"checked": sorted(self.checked)})
        updates.cleanup()
        e.Skip()


class SettingsDialog(wx.Dialog):
    def __init__(self, parent, cfg):
        super().__init__(parent, title="Settings", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        s = wx.BoxSizer(wx.VERTICAL)

        def stacked(label, ctrl, tip, grow=False):
            ctrl_label = wx.StaticText(self, label=label)   # made before the control on purpose
            s.Add(ctrl_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
            return ctrl_label

        # Save libraries in
        stacked("Save libraries in:", None, "")
        self.out = wx.TextCtrl(self, value=cfg["out_dir"], style=wx.TE_READONLY, size=(460, -1))
        speech.label(self.out, "Save libraries in")
        self.out.SetToolTip("The folder libraries and reports are saved in. Each maker gets its own folder inside.")
        s.Add(self.out, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        b = wx.Button(self, label="Change Folder...")
        b.SetToolTip("Choose another folder for libraries and reports.")
        b.Bind(wx.EVT_BUTTON, self.on_folder)
        s.Add(b, 0, wx.ALL, 6)

        stacked("Your name in file names:", None, "")
        self.author = wx.TextCtrl(self, value=cfg["author"])
        speech.label(self.author, "Your name in file names")
        self.author.SetToolTip('Files are named like "bx_glue VST3 by Your Name.RPL", the way shared libraries are '
                               'often named. Leave it empty for "bx_glue VST3.RPL".')
        s.Add(self.author, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        stacked("Smallest library worth keeping, in working presets:", None, "")
        self.min = wx.SpinCtrl(self, min=1, max=50, initial=int(cfg["min_keep"]))
        speech.label(self.min, "Smallest library worth keeping, in working presets")
        self.min.SetToolTip("A library with fewer working presets than this isn't saved; the report says so. "
                            "5 is the usual choice.")
        s.Add(self.min, 0, wx.LEFT | wx.RIGHT, 8)

        self.twice = wx.CheckBox(self, label="Check each library twice")
        self.twice.SetValue(bool(cfg["check_twice"]))
        self.twice.SetToolTip("After the first check, the finished library is loaded and checked again, and "
                              "anything that fails the second time is left out too. Takes about twice as long; "
                              "catches presets that only load sometimes.")
        s.Add(self.twice, 0, wx.ALL, 8)

        self.split = wx.CheckBox(self, label="Split big sets into one library per folder")
        self.split.SetValue(bool(cfg["split_big"]))
        self.split.SetToolTip("When a plug-in has more presets than the number below and they sit in several "
                              "folders (an ADpak, a Pianoteq instrument), each folder becomes its own library, "
                              "so you can import just the ones you want. Only the first has 0 Default settings.")
        s.Add(self.split, 0, wx.ALL, 8)
        stacked("Split when a plug-in has more presets than:", None, "")
        self.split_over = wx.SpinCtrl(self, min=20, max=100000, initial=int(cfg["split_over"]))
        speech.label(self.split_over, "Split when a plug-in has more presets than")
        self.split_over.SetToolTip("Below this many, a plug-in's presets stay in one library even if they're "
                                   "in several folders.")
        s.Add(self.split_over, 0, wx.LEFT | wx.RIGHT, 8)

        self.speak = wx.CheckBox(self, label="Say each plug-in's result as it finishes")
        self.speak.SetValue(bool(cfg.get("speak", True)))
        self.speak.SetToolTip("VoiceOver says each library's result when it's done, without moving you. "
                              "The end of a run is always said.")
        s.Add(self.speak, 0, wx.ALL, 8)

        stacked("Also look for presets in:", None, "")
        self.folders = wx.ListBox(self, choices=list(cfg.get("extra_folders", [])), size=(460, 90))
        speech.label(self.folders, "Also look for presets in")
        self.folders.SetToolTip("Folders looked in besides the usual places, such as a Native Instruments "
                                "User Content folder on another drive.")
        s.Add(self.folders, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        row = wx.BoxSizer(wx.HORIZONTAL)
        ba = wx.Button(self, label="Add Folder...")
        ba.SetToolTip("Add a folder to look for presets in.")
        br = wx.Button(self, label="Remove Folder")
        br.SetToolTip("Stop looking in the selected folder.")
        ba.Bind(wx.EVT_BUTTON, self.on_add)
        br.Bind(wx.EVT_BUTTON, self.on_remove)
        row.Add(ba, 0, wx.ALL, 4)
        row.Add(br, 0, wx.ALL, 4)
        s.Add(row, 0, wx.LEFT, 4)

        btns = wx.StdDialogButtonSizer()
        ok = wx.Button(self, wx.ID_OK, "Save")
        ok.SetToolTip("Keeps these settings.")
        cancel = wx.Button(self, wx.ID_CANCEL, "Cancel")
        cancel.SetToolTip("Closes without changing anything (Escape).")
        btns.AddButton(ok)
        btns.AddButton(cancel)
        btns.Realize()
        s.Add(btns, 0, wx.EXPAND | wx.ALL, 8)
        self.SetEscapeId(wx.ID_CANCEL)
        self.SetSizerAndFit(s)
        self.out.SetFocus()

    def on_folder(self, e):
        dlg = wx.DirDialog(self, "Save libraries in", self.out.GetValue())
        if dlg.ShowModal() == wx.ID_OK:
            self.out.SetValue(dlg.GetPath())
        dlg.Destroy()

    def on_add(self, e):
        dlg = wx.DirDialog(self, "Also look for presets in")
        if dlg.ShowModal() == wx.ID_OK and dlg.GetPath() not in self.folders.GetItems():
            self.folders.Append(dlg.GetPath())
        dlg.Destroy()

    def on_remove(self, e):
        i = self.folders.GetSelection()
        if i != wx.NOT_FOUND:
            self.folders.Delete(i)

    def values(self):
        return {"out_dir": self.out.GetValue(), "author": self.author.GetValue().strip(),
                "min_keep": self.min.GetValue(), "check_twice": self.twice.GetValue(),
                "split_big": self.split.GetValue(), "split_over": self.split_over.GetValue(),
                "speak": self.speak.GetValue(), "extra_folders": list(self.folders.GetItems())}


ACCESS_WORDS = ("Some plug-ins look through your Documents folder or other drives as they load. The first time "
                "the checking copy of REAPER does that, macOS stops it and asks whether REAPER for checking presets "
                "can open files there, and checking waits until you answer.\n\nStart opens each place once now, "
                "so the questions come together while you're here. Choose Allow for each. Nothing is changed in "
                "any folder; you can take the access back any time in System Settings, Privacy and Security, "
                "Files and Folders.")

HOW_CHECKED = """Each plug-in is loaded in a separate copy of REAPER, hidden and silent, made from your REAPER. Your own REAPER, its settings and its presets are never touched.

Every preset is chosen by name from REAPER's preset list, and the plug-in is asked to save its settings back. A preset stays only if REAPER chose it by name and the plug-in's own saved settings match what the preset file holds. A setting snapping to the plug-in's own control steps counts as a match. When the plug-in's format can't be read, the preset must at least move the plug-in's controls away from their defaults; the report says which presets were checked that way.

Then the finished library is checked again, and anything that fails the second time is left out too. A library with fewer working presets than the smallest worth keeping isn't saved. Each library starts with 0 Default settings, the plug-in as it loads fresh."""

ABOUT = f"""{APP_NAME} {VERSION}

Makes REAPER preset libraries from the factory presets your plug-ins installed, and keeps only the presets REAPER really loads.

Magpie is a working name. Not affiliated with Cockos or with any plug-in maker."""


def main():
    app = wx.App()
    app.SetAppName(APP_NAME)
    one = wx.SingleInstanceChecker(APP_NAME + "-" + wx.GetUserId())
    if one.IsAnotherRunning():   # one window at a time can use the checking copy of REAPER
        speech.announce(f"{APP_NAME} is already open.")
        return
    f = MainFrame()
    f.Show()
    app.MainLoop()
    del one
