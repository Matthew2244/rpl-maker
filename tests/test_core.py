"""Tests that need no REAPER and no plug-ins: formats, states, files, judging, wording."""
import base64
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rplmaker import compare, formats, inventory, pipeline, states  # noqa: E402


def fake_default(comp=b"COMP", ctrl=b""):
    prefix = b"\x01\x02\x03\x04" * 4
    data = states.payload({"prefix": prefix, "marker": b"\xff\xff\x10\x00"}, comp, "x", ctrl)
    return states.parse_state(data)


class States(unittest.TestCase):
    def test_payload_round_trip(self):
        st = fake_default(b"hello", b"ctl")
        self.assertEqual(st["comp"], b"hello")
        self.assertEqual(st["ctrl"], b"ctl")
        data = states.payload(st, b"other state", "Preset", b"")
        back = states.parse_state(data)
        self.assertEqual(back["comp"], b"other state")
        self.assertEqual(back["prefix"], st["prefix"])
        self.assertIn(b"\x00Preset\x00", back["tail"])

    def test_prefix_with_ff_ff_inside(self):
        prefix = b"\xff\xff\x00\x00" + b"\x00" * 12   # a pin layout that contains the marker bytes
        data = states.payload({"prefix": prefix, "marker": b"\xff\xff\x10\x00"}, b"abc", "n")
        self.assertEqual(states.parse_state(data)["comp"], b"abc")

    def test_rpl_round_trip_and_quotes(self):
        presets = [("0 Default settings", b"\x00" * 300), ('Say "hi"', b"abc"), ("it's `odd`", b"q")]
        text = states.rpl_text('VST3: X (Y)', presets)
        plug, back = states.parse_rpl(text)
        self.assertEqual(plug, "VST3: X (Y)")
        self.assertEqual(back, presets)

    def test_ini_checksum(self):
        text = states.ini_text([("A", bytes(range(10)))])
        self.assertIn("NbPresets=1", text)
        line = [l for l in text.split("\n") if l.startswith("Data=")][0]
        self.assertEqual(line, "Data=" + bytes(range(10)).hex().upper() + format(sum(range(10)) & 255, "02X"))

    def test_juce_wrap(self):
        head = b"FBCh" + struct.pack(">IIII", 1, 0, 1, 1) + b"\x00" * 128
        bank_body = head + struct.pack(">I", 3) + b"old"
        default = b"VstW" + struct.pack(">I", 8) + b"\x00" * 8 + b"CcnK" + struct.pack(">I", len(bank_body)) + bank_body + b"JUCEPrivate"
        self.assertTrue(states.is_juce(default))
        new = states.juce_wrap(default, b"brand new chunk")
        self.assertEqual(states.juce_split(new)[2], b"brand new chunk")
        self.assertTrue(new.endswith(b"JUCEPrivate"))

    def test_unique_names(self):
        self.assertEqual(states.unique_names(["A", "a", "B", "A"]), ["A", "a (2)", "B", "A (3)"])


class Formats(unittest.TestCase):
    def test_msgpack(self):
        b = b"\x83\xa4name\xa5Hello\xa9VST.magic\xceNi$Q\xa8VST3.uid\x94\x01\x02\x03\x04"
        d, _ = formats.msgpack(b)
        self.assertEqual(d["name"], "Hello")
        self.assertEqual(formats.fourcc_hex(d["VST.magic"]), b"Ni$Q".hex().upper())
        self.assertEqual(d["VST3.uid"], [1, 2, 3, 4])

    def test_vstpreset_read(self):
        cls = "ABCDEF019182FAEB786C6E4178414432"
        comp = b"component"
        body = b"VST3" + struct.pack("<I", 1) + cls.encode() + struct.pack("<Q", 48)
        listing = b"List" + struct.pack("<I", 1) + b"Comp" + struct.pack("<QQ", 48 + 8 + 20, len(comp))
        data = body + listing + comp
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "My Preset.vstpreset")
            with open(p, "wb") as f:
                f.write(data)
            fd = formats.read(p)
            self.assertEqual(fd.class_id, cls)
            self.assertEqual(fd.name, "My Preset")
            comp2, ctrl = formats.make_state(fd, fake_default())
            self.assertEqual(comp2, comp)

    def test_fxp_chunk_raw_and_juce(self):
        chunk = b"<patch/>"
        fxp = (b"CcnK" + struct.pack(">I", 0) + b"FPCh" + struct.pack(">II", 1, 0x636a7333) + struct.pack(">II", 1, 1)
               + b"Name".ljust(28, b"\x00") + struct.pack(">I", len(chunk)) + chunk)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "Lead.fxp")
            with open(p, "wb") as f:
                f.write(fxp)
            fd = formats.read(p)
            self.assertEqual(fd.vst2, "636A7333")
            self.assertEqual(formats.make_state(fd, fake_default(b"plain"))[0], chunk)


class Naming(unittest.TestCase):
    def test_split_display(self):
        self.assertEqual(inventory.split_display("Pianoteq 9 (Modartt) (1->16ch)"), ("Pianoteq 9", "Modartt"))
        self.assertEqual(inventory.split_display("UADx 1176 (Universal Audio (UADx))"),
                         ("UADx 1176", "Universal Audio (UADx)"))
        self.assertEqual(inventory.split_display("Addictive Drums 2 (XLN Audio) (18 out)"),
                         ("Addictive Drums 2", "XLN Audio"))
        # a bridged Intel plug-in: REAPER puts the architecture before the maker
        self.assertEqual(inventory.split_display("Philharmonik 2 (x86_64) (IK Multimedia) (32 out)"),
                         ("Philharmonik 2", "IK Multimedia"))

    def test_preset_names_folders(self):
        F = formats.Found
        found = [F("/p/Mixing/Glue.vstpreset", "vstpreset", "Glue"),
                 F("/p/Mastering/Gentle.vstpreset", "vstpreset", "Gentle"),
                 F("/p/Funk/Funk - Big Funk.nksf", "nks", "Funk - Big Funk")]
        self.assertEqual(pipeline.preset_names(found), ["Mixing - Glue", "Mastering - Gentle", "Funk - Big Funk"])

    def test_file_name(self):
        p = inventory.Plugin("VST3: a/b (V)", "a/b", "V", "0" * 32, "x.vst3", False)
        self.assertEqual(pipeline.file_name(p, "Sam"), "a-b VST3 by Sam.RPL")
        self.assertEqual(pipeline.file_name(p, ""), "a-b VST3.RPL")

    def test_file_names_every_system_can_save(self):
        self.assertEqual(pipeline.safe_file_name('A "B" <C>|D?*.'), "A -B- -C--D--")
        self.assertEqual(pipeline.safe_file_name(" ... "), "Untitled")

    def test_report_on_every_system(self):
        # %-d and %-I stop strftime on Windows; the report spells the date out itself
        import datetime
        p = inventory.Plugin("VST3: Glue (V)", "Glue", "V", "0" * 32, "x.vst3", False)
        r = pipeline.Result(p, status="made", kept=[("a", "exact")] * 6,
                            files=[("/out/V/Glue 1.RPL", 3), ("/out/V/Glue 2.RPL", 3)])
        text = pipeline.report_text([r, pipeline.Result(p, status="skipped")], "/out",
                                    datetime.datetime(2026, 11, 5, 9, 7))
        self.assertTrue(text.startswith("Preset libraries made Thursday 5 November 2026 at 9:07 AM"), text[:80])
        self.assertIn("2 libraries made for 1 of 2 plug-ins, 6 working presets in all.", text)

    def test_checking_copy_looks_where_your_reaper_looks(self):
        from rplmaker import portable
        with tempfile.TemporaryDirectory() as d:
            self.assertIn("vstpath64=", portable.ini_text(d))       # no reaper.ini: this app's own
            with open(os.path.join(d, "reaper.ini"), "w") as f:
                f.write("[audio]\nvstpath64=nope\n[REAPER]\nvstpath64=/Volumes/Plugs/VST3\nvstpath_arm64=\n")
            text = portable.ini_text(d)
            self.assertIn("vstpath64=/Volumes/Plugs/VST3\n", text)
            self.assertNotIn("nope", text)
            self.assertEqual(text.count("vstpath64="), 1)

    def test_checking_copy_never_asks_for_an_audio_device(self):
        from unittest import mock
        from rplmaker import portable
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "reaper.ini"), "w") as f:
                f.write("[REAPER]\nverchk=1\n[nag]\nnag=ABC123\n[audioconfig]\nmode=5\n")
            with mock.patch.object(portable, "WIN", True):
                text = portable.full_ini(d)
                self.assertIn("[audioconfig]\nmode=4\n", text)      # Dummy Audio: no device, no question
                self.assertNotIn("mode=5", text)                      # never your own audio settings
                self.assertNotIn("coreaudio", text)
            with mock.patch.object(portable, "WIN", False):
                text = portable.full_ini(d, mac_device="Quiet Out")
                self.assertIn("coreaudiooutdevnew=Quiet Out\n", text)
                self.assertNotIn("[audioconfig]", text)
            self.assertIn("[nag]\nnag=ABC123\n", text)            # REAPER's licence-agreement note, read
            # sections in order: the device keys sit in [REAPER] on the Mac, never under [nag]
            self.assertLess(text.index("coreaudiooutdevnew"), text.index("[nag]"))
        with tempfile.TemporaryDirectory() as d:                     # a REAPER never opened
            self.assertNotIn("[nag]", portable.full_ini(d))

    def test_documents_folder_is_real(self):
        # on Windows it's asked of the system (OneDrive often moves it)
        if sys.platform == "win32":
            self.assertTrue(os.path.isdir(inventory.documents()))
        else:
            self.assertEqual(inventory.documents(), os.path.join(inventory.HOME, "Documents"))

    def test_grouped_reasons(self):
        cut = [("A", "same"), ("B", "same"), ("C", "other")]
        lines = pipeline.reason_lines(cut)
        self.assertEqual(lines[0], "2 left out because same: A, B.")
        self.assertEqual(lines[1], "Left out: C: other.")


class Judging(unittest.TestCase):
    def line(self, k, name, comp, pv="0.1"):
        st = fake_default()
        data = states.payload(st, comp, name)
        blk = base64.b64encode(data).decode()
        return f"P\t{k}\ttrue\t{k}\t{name}\t{pv}\t{blk}", data

    def test_exact(self):
        line, data = self.line(1, "A", b"xyz")
        self.assertEqual(compare.judge("A", 1, data, line, fake_default(), "0.5").how, "exact")

    def test_wrong_name(self):
        line, data = self.line(1, "B", b"xyz")
        v = compare.judge("A", 1, data, line, fake_default(), "0.5")
        self.assertFalse(v.ok)
        self.assertIn("by name", v.why)

    def test_xml_values_and_rounding(self):
        st = fake_default()
        src = states.payload(st, b'<s a="0.3512" b="x"/>', "A")
        got_line, _ = self.line(1, "A", b'<s a="0.3495" b="x" uiWidth="300"/>')
        self.assertEqual(compare.judge("A", 1, src, got_line, st, "0.5").how, "rounded")
        bad_line, _ = self.line(1, "A", b'<s a="0.9" b="x"/>')
        self.assertFalse(compare.judge("A", 1, src, bad_line, st, "0.5").ok)

    def test_opaque_controls(self):
        st = fake_default(b"\x01\x02default")
        src = states.payload(st, b"\x09\x09opaque", "A")
        moved, _ = self.line(1, "A", b"\x09\x09opaque-resaved", pv="0.9")
        self.assertEqual(compare.judge("A", 1, src, moved, st, "0.5").how, "controls")
        still, _ = self.line(1, "A", b"\x09\x09opaque-resaved", pv="0.5")
        self.assertFalse(compare.judge("A", 1, src, still, st, "0.5").ok)


if __name__ == "__main__":
    unittest.main()


class OpaqueDuplicates(unittest.TestCase):
    def test_different_files_same_result_kept_once(self):
        st = fake_default(b"\x01default")
        b = pipeline.Builder("/nonexistent")
        presets = [("0 Default settings", states.payload(st, st["comp"], "0 Default settings"))]
        got = {}
        for k, (name, src, resaved, pv) in enumerate([("A", b"\x09a", b"\x09same", "0.9"),
                                                      ("B", b"\x09b", b"\x09same", "0.9"),
                                                      ("C", b"\x09c", b"\x09other", "0.8")], start=1):
            data = states.payload(st, src, name)
            presets.append((name, data))
            blk = base64.b64encode(states.payload(st, resaved, name)).decode()
            got[k] = f"P\t{k}\ttrue\t{k}\t{name}\t{pv}\t{blk}"
        got[0] = "P\t0\ttrue\t0\t0 Default settings\t0.5\t" + base64.b64encode(presets[0][1]).decode()
        v = b._judge_all(presets, got, st, "0.5")
        self.assertTrue(v[1].ok)
        self.assertFalse(v[2].ok)
        self.assertIn("ends up exactly as it does for A", v[2].why)
        self.assertTrue(v[3].ok)

    def test_split_merges_small_folders(self):
        b = pipeline.Builder("/x", min_keep=5, split_over=10)
        kept = [(f"p{i}", b"") for i in range(30)]
        groups = {f"p{i}": ("Big" if i < 23 else "S1" if i < 26 else "S2") for i in range(30)}
        parts = dict(b._parts(kept, groups))
        self.assertEqual(len(parts["Big"]), 23)
        self.assertEqual(len(parts["Other folders"]), 7)


class Variants(unittest.TestCase):
    def test_variant_kept_in_name(self):
        self.assertEqual(inventory.split_display("Blue Cat's Gain 3 (Dual) (Blue Cat Audio)"),
                         ("Blue Cat's Gain 3 (Dual)", "Blue Cat Audio"))
        self.assertEqual(inventory.split_display("Unfiltered Audio G8 (Plugin Alliance) (4ch)"),
                         ("Unfiltered Audio G8", "Plugin Alliance"))
        self.assertEqual(inventory.split_display("Plain"), ("Plain", ""))


class Sounds(unittest.TestCase):
    """Nothing is played: _start is replaced by a recorder."""
    def setUp(self):
        from rplmaker import sounds
        self.s = sounds
        self.played = []
        self._orig = sounds._start
        sounds._start = lambda p: self.played.append(os.path.basename(p))
        sounds._state.update(busy_until=0.0, last={})

    def tearDown(self):
        self.s._start = self._orig

    def test_files_exist_for_this_system(self):
        self.assertEqual(self.s.missing(), [])

    def test_speech_waits_for_the_sound(self):
        wait = self.s.play("failed")
        self.assertAlmostEqual(wait, self.s.LENGTH["failed"], places=2)

    def test_second_sound_queues_after_the_first(self):
        self.s.play("library_made")
        wait = self.s.play("done")
        self.assertAlmostEqual(wait, self.s.LENGTH["library_made"] + self.s.GAP + self.s.LENGTH["done"], places=1)

    def test_library_made_at_most_every_two_seconds(self):
        self.s.play("library_made")
        self.s.play("library_made")
        self.assertEqual(len(self.played), 1)

    def test_off_means_silent_and_no_wait(self):
        self.assertEqual(self.s.play("done", enabled=False), 0.0)
        self.assertEqual(self.played, [])


class FolderAccess(unittest.TestCase):
    """The Windows side of folder access, which works anywhere: read, save, explain."""

    def test_all_fine(self):
        from rplmaker import access
        with tempfile.TemporaryDirectory() as d:
            os.mkdir(os.path.join(d, "presets"))
            r = access.check([os.path.join(d, "presets"), os.path.join(d, "not there")], os.path.join(d, "out"),
                             protection=lambda: None)
            self.assertFalse(r.problems)
            self.assertEqual(r.readable, 1)       # a usual place that isn't there is no problem
            self.assertEqual(os.listdir(os.path.join(d, "out")), [])   # the test file is gone
            self.assertIn("read 1 of 1 preset folders.", r.summary())

    def test_problems_named_and_explained(self):
        from rplmaker import access
        with tempfile.TemporaryDirectory() as d:
            blocker = os.path.join(d, "a file")
            with open(blocker, "w") as f:
                f.write("x")
            extra = os.path.join(d, "my presets")
            r = access.check([blocker], os.path.join(blocker, "out"), required=[extra], protection=lambda: "on")
            self.assertTrue(r.problems)
            self.assertFalse(r.can_save)
            names = [n for n, _ in r.unreadable]
            self.assertEqual(names, [blocker, extra])
            text = r.details(os.path.join(blocker, "out"))
            self.assertIn("ransomware protection", text)
            self.assertIn("Allow an app through Controlled folder access", text)
            self.assertIn(extra + ": it isn't there", text)

    def test_protection_on_but_saving_works(self):
        from rplmaker import access
        with tempfile.TemporaryDirectory() as d:
            r = access.check([], d, protection=lambda: "on")
            self.assertFalse(r.problems)
            self.assertIn("nothing needs changing", r.details(d))

    def test_protection_read_never_raises(self):
        from rplmaker import access
        self.assertIn(access.ransomware_protection(), (None, "on", "off", "audit"))


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class WindowsHide(unittest.TestCase):
    def test_hides_a_programs_windows(self):
        import subprocess
        import time
        from rplmaker import portable
        p = subprocess.Popen([sys.executable, "-c", "import tkinter as t; r = t.Tk(); r.title('x'); r.mainloop()"])
        try:
            def visible():
                return [w for w in portable.win_windows(p.pid) if w[3]]
            for _ in range(40):
                time.sleep(0.25)
                if visible():
                    break
            self.assertTrue(visible())
            self.assertEqual(portable._win_hide(p.pid), [])   # a plain window, not a question
            self.assertEqual(visible(), [])                    # nothing visible is left
        finally:
            p.kill()


class AlreadyInReaper(unittest.TestCase):
    """REAPER's own presets files (tests/fixtures/reaper), read to notice plug-ins done by hand."""
    FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "reaper")

    def plug(self, name, names, vendor="Maker Co", bundle=None, cls="0" * 32):
        p = inventory.Plugin(f"VST3: {name} ({vendor})", name, vendor, cls, bundle or name.replace(" ", "_") + ".vst3", False)
        p.presets["vstpreset"] = [formats.Found(f"/x/{n}.vstpreset", "vstpreset", n) for n in names]
        return p

    def resource(self, d):
        import shutil
        res = os.path.join(d, "reaper")
        shutil.copytree(self.FIXTURE, res)
        if sys.platform != "win32":   # a colon can't be in a Windows file name, and AU is Mac-only anyway
            for fn, names in (("au-Maker Co: Synth One.ini", ["Drums - Kick Room", "pads/Warm Pad", "LEAD  bright!", "Bass"]),
                              ("au-Someone Else: Synth Two.ini", ["S 1", "S 2", "S 3", "S 4"])):
                with open(os.path.join(res, "presets", fn), "w") as f:
                    f.write(states.ini_text([(n, b"x") for n in names]))
        return res

    def run_mark(self, plugs):
        from rplmaker import inreaper
        with tempfile.TemporaryDirectory() as d:
            res = self.resource(d)
            before = {f: os.path.getmtime(os.path.join(res, "presets", f)) for f in os.listdir(os.path.join(res, "presets"))}
            inreaper.mark(plugs, res)
            after = {f: os.path.getmtime(os.path.join(res, "presets", f)) for f in os.listdir(os.path.join(res, "presets"))}
            self.assertEqual(before, after)          # REAPER's files are only ever read
        return {p.name: p.in_reaper for p in plugs}

    def test_populated_file_counts_as_done(self):
        from rplmaker import inreaper
        glue = self.plug("Glue Comp", [f"Glue {i}" for i in range(1, 11)])
        got = self.run_mark([glue])["Glue Comp"]
        self.assertTrue(got.done)
        self.assertEqual((got.file, got.fmt, got.matched, got.of, got.named), ("vst3-Glue_Comp.ini", "vst3", 8, 10, 9))
        self.assertTrue(inreaper.detail_lines(got)[0].startswith("Already in REAPER: its presets in REAPER, for the VST3"))
        self.assertEqual(inreaper.status_words(got), "Already in REAPER")

    def test_default_or_blank_entry_is_not_done(self):
        # almost every plug-in gets a presets file once it's been used, often holding one
        # Default or blank entry: that's never someone's work
        r = self.run_mark([self.plug("Surgish", ["default", "Bass 1", "Pad 2", "Lead 3"]),
                           self.plug("Blanky", ["A", "B", "C"])])
        self.assertIsNone(r["Surgish"])
        self.assertIsNone(r["Blanky"])

    def test_a_couple_of_presets_or_under_half_is_not_done(self):
        from rplmaker import inreaper
        r = self.run_mark([self.plug("Fewer", ["F 1", "F 2", "F 3"]),
                           self.plug("Halfway", [f"H {i}" for i in range(1, 11)])])
        self.assertEqual((r["Fewer"].matched, r["Fewer"].done), (2, False))      # needs at least 3
        self.assertEqual((r["Halfway"].matched, r["Halfway"].done), (4, False))  # needs 5 of 10
        self.assertIn("isn't counted as already in REAPER", inreaper.detail_lines(r["Halfway"])[0])

    def test_reapers_factory_cache_never_counts(self):
        self.assertIsNone(self.run_mark([self.plug("Factory", [f"Fac {i}" for i in range(1, 11)])])["Factory"])

    def test_other_formats_match_by_their_own_names(self):
        from rplmaker import inreaper
        two = self.plug("Glue Two", [f"V {i}" for i in range(1, 7)], cls="565354" + "676E6572" + "0" * 18)
        chorus = self.plug("Chorus", ["C 1", "C 2", "C 3", "C 4"], bundle="Maker_Chorus.vst3")
        r = self.run_mark([two, chorus])
        self.assertEqual((r["Glue Two"].fmt, r["Glue Two"].done), ("vst", True))   # VST2, by its unique id
        self.assertEqual((r["Chorus"].fmt, r["Chorus"].done), ("clap", True))      # CLAP, by REAPER's CLAP list
        self.assertEqual(inreaper.status_words(r["Chorus"]), "Already in REAPER for the CLAP version")
        self.assertIn("VST3 version", inreaper.detail_lines(r["Chorus"])[1])

    @unittest.skipIf(sys.platform == "win32", "AU is Mac-only, and its file names hold a colon")
    def test_au_by_maker_and_name_and_folder_names(self):
        one = self.plug("Synth One", ["Kick Room", "Warm Pad", "Lead Bright", "Bass"])
        two = self.plug("Synth Two", ["S 1", "S 2", "S 3", "S 4"])        # same name shape, other maker's file
        r = self.run_mark([one, two])
        self.assertEqual((r["Synth One"].fmt, r["Synth One"].matched, r["Synth One"].done), ("au", 4, True))
        self.assertIsNone(r["Synth Two"])

    def test_identity_rules(self):
        from rplmaker import inreaper
        p = self.plug("Synth One", [], bundle="Synth_One_v1.vst3")
        self.assertTrue(inreaper.is_for(p, "au", "Maker Co: Synth One", {}, {}))
        self.assertTrue(inreaper.is_for(p, "au", "MAKER CO.: synth-one", {}, {}))
        self.assertFalse(inreaper.is_for(p, "au", "Someone Else: Synth One", {}, {}))
        self.assertTrue(inreaper.is_for(p, "vst3", "Synth One v1", {}, {}))      # the bundle's real file name
        self.assertTrue(inreaper.is_for(p, "vst3", "Synth One", {}, {}))         # or the plug-in's name
        self.assertFalse(inreaper.is_for(p, "vst3", "Synth One Effects", {}, {}))
        self.assertFalse(inreaper.is_for(p, "js", "Synth One", {}, {}))

    def test_folder_prefixes_and_dashes_in_names(self):
        from rplmaker import inreaper
        keys_ = inreaper.name_keys(["Brainworx - Mix - BA Bus - Gentle", "Default"])
        for found in ("BA Bus - Gentle", "Mix - BA Bus - Gentle", "Gentle"):
            self.assertIn(inreaper.key(found), keys_)
        self.assertNotIn("default", keys_)

    def test_placeholders(self):
        from rplmaker import inreaper
        for n in ("Default", "default", "0 Default settings", "", "  ", "Init", "Program 3", "Preset 12", "Untitled 2"):
            self.assertTrue(inreaper.placeholder(n), n)
        for n in ("Acoustic Guitar", "Initial Velocity Bass", "Default Room Large", "Glue 1"):
            self.assertFalse(inreaper.placeholder(n), n)

    def test_never_raises(self):
        from rplmaker import inreaper
        p = self.plug("Glue Comp", ["Glue 1"])
        inreaper.mark([p], "/no/such/folder")
        self.assertIsNone(p.in_reaper)


class Shortcuts(unittest.TestCase):
    def test_every_key_means_one_thing(self):
        from rplmaker import keys
        every = [k.lower() for k in keys.every_key()]
        self.assertEqual(len(every), len(set(every)), every)

    def test_reapers_and_osaras_keys(self):
        from rplmaker import keys
        self.assertEqual(keys.SHORTCUTS["preferences"], "Ctrl+P")            # REAPER's Preferences
        self.assertEqual(keys.SHORTCUTS["say_progress"], "Ctrl+Shift+Space")  # OSARA's report selection
        self.assertEqual(keys.ALSO["preferences"], ["Ctrl+,"])
        self.assertEqual(keys.say("say_progress", mac=True), "Command-Shift-Space")
        self.assertEqual(keys.say("say_progress", mac=False), "Control+Shift+Space")
        self.assertEqual(keys.words("Ctrl+.", mac=False), "Control+Period")
        # none of macOS's own: Control+Space and Control+Option+Space switch input sources,
        # Command+Space is Spotlight, Command+Option+Space a Finder search
        for taken in ("RawCtrl+Space", "RawCtrl+Alt+Space", "Ctrl+Space", "Ctrl+Alt+Space"):
            self.assertNotIn(taken.lower(), [k.lower() for k in keys.every_key()])


class Organizing(unittest.TestCase):
    """Categories from the maker only, names that sort into groups, a folder tree, names every
    system can save, and organizing libraries that already exist."""
    F = formats.Found

    def test_categories_from_folders(self):
        from rplmaker import organize
        r = "/Library/Audio/Presets/Maker/Synth/"
        found = [self.F(r + "Bass/Deep.nksf", "nks", "Deep", category="Lead"),
                 self.F(r + "Bass/Sub/Round.nksf", "nks", "Round"),
                 self.F(r + "Pads/Warm.nksf", "nks", "Warm"),
                 self.F(r + "Keys/Soft.nksf", "nks", "Soft")]
        # folders win over what's inside the files
        self.assertEqual(organize.categories(found), ["Bass", "Bass - Sub", "Pads", "Keys"])
        self.assertEqual(organize.source(found), "folders")
        self.assertEqual(organize.preset_groups(found), ["Bass", "Bass", "Pads", "Keys"])   # split by the top folder

    def test_categories_from_inside_the_files(self):
        from rplmaker import organize
        found = [self.F("/p/a.nksf", "nks", "Deep", category="Bass"),
                 self.F("/p/b.nksf", "nks", "Saw", category="Synth Lead"),
                 self.F("/p/c.nksf", "nks", "Odd")]
        self.assertEqual(organize.categories(found), ["Bass", "Synth Lead", ""])
        self.assertEqual(organize.preset_names(found), ["Bass - Deep", "Synth Lead - Saw", "Odd"])
        self.assertEqual(organize.preset_names(found, prefix=False), ["Deep", "Saw", "Odd"])
        # one category on every preset says nothing: never used
        same = [self.F("/p/a.nksf", "nks", "A", category="EQ"), self.F("/p/b.nksf", "nks", "B", category="EQ")]
        self.assertEqual(organize.preset_names(same), ["A", "B"])
        self.assertEqual(organize.source(same), "")

    def test_nks_category_is_the_first_sound_type(self):
        self.assertEqual(formats.nks_category({"types": [["Bass", "Bass Line"], ["Synth Lead"]]}), "Bass")
        self.assertIsNone(formats.nks_category({"types": []}))
        self.assertIsNone(formats.nks_category({}))
        self.assertIsNone(formats.nks_category({"types": [[" "]]}))

    def test_vstpreset_category_from_metainfo(self):
        cls = "ABCDEF019182FAEB786C6E4178414432"
        comp = b"component"
        info = (b'<?xml version="1.0"?><MetaInfo><Attribute id="PlugInCategory" value="Fx|EQ" type="string"/>'
                b'<Attribute id="MusicalInstrument" value="Piano|A. Piano" type="string"/></MetaInfo>')
        head = b"VST3" + struct.pack("<I", 1) + cls.encode()
        lst = 48 + len(comp) + len(info)
        data = (head + struct.pack("<Q", lst) + comp + info + b"List" + struct.pack("<I", 2)
                + b"Comp" + struct.pack("<QQ", 48, len(comp)) + b"Info" + struct.pack("<QQ", 48 + len(comp), len(info)))
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "Felt.vstpreset")
            with open(p, "wb") as f:
                f.write(data)
            fd = formats.read(p)
            self.assertEqual(fd.category, "Piano")      # the plug-in's own category isn't the preset's
            self.assertEqual(formats.make_state(fd, fake_default())[0], comp)

    def test_never_twice(self):
        from rplmaker import organize
        P = organize.prefixed
        self.assertEqual(P("Bass", "Deep Sub"), "Bass - Deep Sub")
        for already in ("Bass - Deep", "Bass-Deep", "BASS_Deep", "Bass: Deep", "Bass"):
            self.assertEqual(P("Bass", already), already)
        self.assertEqual(P("Bass", "Bassline"), "Bass - Bassline")        # a word, not a category
        self.assertEqual(P("Funk - Live", "Live - Groove"), "Funk - Live - Groove")
        self.assertEqual(P("", "  Plain "), "Plain")

    def test_names_sort_into_groups_and_stay_unique(self):
        from rplmaker import organize
        names = ["Lead - Saw", "0 Default settings", "Bass - Round", "bass - Deep", "Lead - Saw"]
        got = sorted(states.unique_names(names), key=organize.sort_key)
        self.assertEqual(got, ["0 Default settings", "bass - Deep", "Bass - Round", "Lead - Saw", "Lead - Saw (2)"])

    def test_folder_tree(self):
        from rplmaker import organize
        j = os.path.join
        self.assertEqual(organize.library_dir("/out", "Plugin Alliance", "bx_glue"), j("/out", "Plugin Alliance", "bx_glue"))
        self.assertEqual(organize.library_dir("/out", "Plugin Alliance", "bx_glue", "maker"), j("/out", "Plugin Alliance"))
        self.assertEqual(organize.library_dir("/out", "", "A/B"), j("/out", "Other", "A-B"))

    def test_names_windows_can_save(self):
        from rplmaker import organize
        S = organize.safe_name
        self.assertEqual(S("CON"), "CON_")
        self.assertEqual(S("nul.txt"), "nul.txt_")
        self.assertEqual(S("COM1 "), "COM1_")
        self.assertEqual(S("Console"), "Console")
        self.assertEqual(S("a" * 300), "a" * organize.FILE_LIMIT)
        self.assertEqual(len(S("b" * 300, organize.FOLDER_LIMIT)), organize.FOLDER_LIMIT)
        self.assertEqual(S("Café"), "Café")         # composed, as every system shows it
        self.assertEqual(S("Piano/Keys: Soft?"), "Piano-Keys- Soft-")

    def test_split_per_category(self):
        b = pipeline.Builder("/x", min_keep=2, split_over=300, per_category=True)
        b._other = "Other"
        kept = [(f"p{i}", b"") for i in range(9)]
        groups = {f"p{i}": ("Bass" if i < 4 else "Lead" if i < 8 else "") for i in range(9)}
        parts = b._parts(kept, groups)
        self.assertEqual([(lab, len(items)) for lab, items in parts], [("Bass", 4), ("Lead", 4), ("Other", 1)])
        b.per_category = False
        self.assertEqual(len(b._parts(kept, groups)), 1)   # small set, not asked: one library

    def test_a_library_already_in_groups_is_left_alone(self):
        from rplmaker import organize
        cmap = {"clean": "Addictive Drums 2 - Kit", "dry": "Addictive Drums 2 - Kit"}
        text = states.rpl_text("VST3i: AD2 (XLN)", [("Kit - Clean", b"1"), ("Kit - Dry", b"2"), ("Clean", b"3")])
        self.assertFalse(organize.already_grouped(["Kit - Clean", "Clean", "Dry"]))
        self.assertTrue(organize.already_grouped(["0 Default settings", "Kit - Clean", "Kit - Dry"]))
        _, rows, renamed = organize.organize_library(states.rpl_text("VST3i: AD2 (XLN)", [
            ("Kit - Clean", b"1"), ("Kit - Dry", b"2"), ("Kit - Wet", b"3"), ("Kit - Room", b"4"), ("Clean", b"5")]), cmap)
        self.assertEqual(renamed, 0)
        _, rows, renamed = organize.organize_library(text, {"clean": "Kit"})
        self.assertEqual([r[0] for r in rows], ["Kit - Clean", "Kit - Clean (2)", "Kit - Dry"])   # never two the same

    def test_plugin_of(self):
        from rplmaker import organize
        self.assertEqual(organize.plugin_of("VST3i: Knif Audio Knifonium (Plugin Alliance)"),
                         ("Knif Audio Knifonium", "Plugin Alliance"))
        self.assertEqual(organize.plugin_of("VST3: UADx 1176 (Universal Audio (UADx))"),
                         ("UADx 1176", "Universal Audio (UADx)"))
        self.assertEqual(organize.plugin_of("AU: Apple: AUDelay"), ("AUDelay", "Apple"))
        self.assertEqual(organize.category_file_name("Knifonium VST3i by Sam", "Bass"), "Knifonium - Bass VST3i by Sam")
        self.assertEqual(organize.category_file_name("odd name", "Bass"), "odd name - Bass")

    def test_organize_existing_libraries(self):
        from rplmaker import organize
        st = fake_default()
        def pay(name):
            return states.payload(st, b"S-" + name.encode(), name)
        names = ["0 Default settings", "Deep", "Saw", "Bass - Round", "Odd"]
        text = states.rpl_text("VST3i: Synth (Maker)", [(n, pay(n)) for n in names])
        plug = inventory.Plugin("VST3i: Synth (Maker)", "Synth", "Maker", "1" * 32, "s.vst3", True)
        plug.presets["nks"] = [self.F("/i/a.nksf", "nks", "Deep", category="Bass"),
                               self.F("/i/b.nksf", "nks", "Saw", category="Lead"),
                               self.F("/i/c.nksf", "nks", "Round", category="Bass")]
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "Mine")
            os.makedirs(os.path.join(src, "Brand"))
            with open(os.path.join(src, "Synth VSTi by Sam.RPL"), "w") as f:
                f.write(text)
            with open(os.path.join(src, "Brand", "Synth VST3i by Sam.RPL"), "w") as f:
                f.write(text)
            with open(os.path.join(src, "README.txt"), "w") as f:
                f.write("hello")
            def read(path, mode="rb"):
                with open(path, mode) as fh:
                    return fh.read()
            before = {p: read(os.path.join(src, p)) for p in ("README.txt", "Synth VSTi by Sam.RPL")}
            dst = organize.organized_name(src)
            self.assertTrue(dst.endswith("Mine (organized)"))
            stats = organize.organize_folder(src, dst, [plug])
            self.assertEqual((stats["libraries"], stats["renamed"], stats["copied"]), (2, 4, 1))
            # at the top: its maker's folder, then the plug-in's; in a folder: that folder kept
            top = os.path.join(dst, "Maker", "Synth", "Synth VSTi by Sam.RPL")
            kept = os.path.join(dst, "Brand", "Synth", "Synth VST3i by Sam.RPL")
            _, got = states.parse_rpl(read(top, "r"))
            self.assertEqual([n for n, _ in got], ["0 Default settings", "Bass - Deep", "Bass - Round", "Lead - Saw", "Odd"])
            for n, data in got:
                self.assertTrue(data.endswith(b"\x00" + n.encode() + b"\x00\x10\x00\x00\x00"), n)   # the new name inside
            old = {states.parse_state(p)["comp"] for _, p in states.parse_rpl(text)[1]}
            self.assertEqual({states.parse_state(p)["comp"] for _, p in got}, old)   # the sounds untouched
            self.assertTrue(os.path.exists(kept))
            self.assertTrue(os.path.exists(os.path.join(dst, "README.txt")))
            for p, b in before.items():                                          # the original never changed
                self.assertEqual(read(os.path.join(src, p)), b)
            # one library per category; the default only in the first
            dst2 = organize.organized_name(src)
            self.assertTrue(dst2.endswith("Mine (organized 2)"))
            organize.organize_folder(src, dst2, [plug], per_category=True, min_keep=1)
            folder = os.path.join(dst2, "Maker", "Synth")
            self.assertEqual(sorted(os.listdir(folder)), ["Synth - Bass VSTi by Sam.RPL", "Synth - Lead VSTi by Sam.RPL",
                                                          "Synth - Other VSTi by Sam.RPL"])
            # a category smaller than a library worth keeping joins Other
            dst4 = os.path.join(d, "min2")
            organize.organize_folder(src, dst4, [plug], per_category=True, min_keep=2)
            folder = os.path.join(dst4, "Maker", "Synth")
            self.assertEqual(sorted(os.listdir(folder)), ["Synth - Bass VSTi by Sam.RPL", "Synth - Other VSTi by Sam.RPL"])
            _, bass = states.parse_rpl(read(os.path.join(folder, "Synth - Bass VSTi by Sam.RPL"), "r"))
            _, other = states.parse_rpl(read(os.path.join(folder, "Synth - Other VSTi by Sam.RPL"), "r"))
            self.assertEqual([n for n, _ in bass], ["0 Default settings", "Bass - Deep", "Bass - Round"])
            self.assertEqual(sorted(n for n, _ in other), ["Lead - Saw", "Odd"])
            # without the plug-in here, nothing is renamed: only the folders change
            dst3 = os.path.join(d, "plain")
            stats = organize.organize_folder(src, dst3, [])
            self.assertEqual(stats["renamed"], 0)
            with self.assertRaises(ValueError):
                organize.organize_folder(src, os.path.join(src, "inside"), [])


class NotScannedYet(unittest.TestCase):
    """Plug-ins installed since REAPER last started aren't in its plug-in list. The checking
    copy scans them, keeps what it found, and they're offered like any other."""

    YOURS = ("[vstcache]\n"
             "Ozone.vst3=00AA,123{" + "A" * 32 + ",Ozone (iZotope)\n"
             "Broken_Thing.vst3=00BB\n")     # REAPER tried it and it failed: never tried again
    COPYS = ("[vstcache]\n"
             "Ozone.vst3=00AA,123{" + "A" * 32 + ",Ozone (iZotope)\n"
             "MODO_DRUM.vst3=00CC,456{" + "B" * 32 + ",MODO DRUM (IK Multimedia)!!!VSTi\n"
             "Hammond_B_3X.vst3=00DD\n")     # the copy was cut off mid-scan: try it again

    def _dirs(self):
        root = tempfile.mkdtemp()
        yours, copy, vst3 = (os.path.join(root, n) for n in ("yours", "copy", "VST3"))
        for d in (yours, copy, vst3):
            os.makedirs(d)
        with open(os.path.join(yours, "reaper-vstplugins64.ini"), "w") as f:
            f.write(self.YOURS)
        with open(os.path.join(copy, "reaper-vstplugins64.ini"), "w") as f:
            f.write(self.COPYS)
        with open(os.path.join(yours, "reaper.ini"), "w") as f:
            f.write(f"[REAPER]\nvstpath64={vst3}\nvstpath_arm64={vst3}\n")
        for b in ("Ozone.vst3", "Broken Thing.vst3", "MODO DRUM.vst3", "Hammond B-3X.vst3", "SampleTank 4.vst3"):
            os.makedirs(os.path.join(vst3, b, "Contents"))
        return yours, copy

    def test_merge_keeps_only_finished_scans_of_the_copy(self):
        from rplmaker import portable
        text = portable.merge_plugin_lists(self.YOURS, self.COPYS)
        self.assertTrue(text.startswith(self.YOURS))
        self.assertIn("MODO_DRUM.vst3=00CC", text)
        self.assertNotIn("Hammond_B_3X", text)
        self.assertEqual(text.count("Ozone.vst3="), 1)

    def test_plugins_the_copy_scanned_are_offered_and_marked(self):
        yours, copy = self._dirs()
        plugs = {p.name: p for p in inventory.plugins(yours, checker=copy)}
        self.assertFalse(plugs["Ozone"].unscanned)
        self.assertTrue(plugs["MODO DRUM"].unscanned)
        self.assertTrue(plugs["MODO DRUM"].instrument)
        self.assertNotIn("MODO DRUM", {p.name for p in inventory.plugins(yours, checker=None)})

    def test_unscanned_files(self):
        yours, copy = self._dirs()
        names = [os.path.basename(p) for p in inventory.unscanned_files(yours, checker=copy)]
        # failed in yours: not again; scanned by the copy: done; cut short in the copy: again
        self.assertEqual(names, ["Hammond B-3X.vst3", "SampleTank 4.vst3"])

    def test_a_test_reaper_never_reads_the_real_checking_copy(self):
        yours, _copy = self._dirs()
        self.assertIsNone(inventory._checker_for(yours, "auto"))


def _cint(n: int) -> bytes:
    b = abs(n).to_bytes(max(1, (abs(n).bit_length() + 7) // 8), "little")
    return bytes([len(b) | (0x80 if n < 0 else 0)]) + b


def _vt(name: str, props: dict, kids=()) -> bytes:
    """A juce::ValueTree as ValueTree::writeToStream writes it (enough types for the tests)."""
    out = name.encode() + b"\x00" + _cint(len(props))
    for k, v in props.items():
        out += k.encode() + b"\x00"
        if isinstance(v, bool):
            out += _cint(1) + bytes([2 if v else 3])
        elif isinstance(v, int):
            out += _cint(5) + b"\x01" + struct.pack("<i", v)
        elif isinstance(v, float):
            out += _cint(9) + b"\x04" + struct.pack("<d", v)
        elif isinstance(v, bytes):
            out += _cint(len(v) + 1) + b"\x08" + v
        else:
            data = v.encode() + b"\x00"
            out += _cint(len(data) + 1) + b"\x05" + data
    out += _cint(len(kids))
    for k in kids:
        out += k
    return out


def _juce_b64(data: bytes) -> str:
    alpha = ".ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+"
    bits = "".join(format(b, "08b")[::-1] for b in data)
    chars = [alpha[int(bits[i:i + 6].ljust(6, "0")[::-1], 2)] for i in range(0, len(bits), 6)]
    return f"{len(data)}." + "".join(chars)


def _vst2_wrapped(chunk: bytes, version: int = 1, fxid: bytes = b"Hamm") -> bytes:
    head = b"FBCh" + struct.pack(">I", 2) + fxid + struct.pack(">II", version, 1) + b"\x00" * 128
    body = head + struct.pack(">I", len(chunk)) + chunk
    return b"VstW" + struct.pack(">III", 8, 1, 0) + b"CcnK" + struct.pack(">I", len(body)) + body


class IKStates(unittest.TestCase):
    """IK Multimedia's VST3 states: plain XML or a binary juce::ValueTree inside the VST2-style
    wrapper, and banks that carry the version of the plug-in that saved them."""

    def test_wrapped_plain_xml_is_read(self):
        comp = _vst2_wrapped(b'<?xml version="1.0"?>\r\n<State><Model Drawbar1="8.0" Split="1.0"/></State>')
        name, vals = compare.decode(comp)
        self.assertEqual(name, "wrapped XML")
        self.assertEqual(vals["State/Model[1]@Split"], "1.0")

    def test_value_tree_with_blocks_inside(self):
        amp = _vt("AmpTubeState", {"Gain": 0.5}) + b"\x01\x02\x03\x04" * 2   # a tree, then raw floats
        tree = _vt("AppState", {"BPM": 90.0, "Model": "P-Bass", "Muted": True, "Strings": 4,
                                "AmpNode": _juce_b64(amp), "GuiScale": "1.0"},
                   [_vt("Child", {"Level": -3.0})])
        comp = _vst2_wrapped(tree + b"\x00" * 8 + b"JUCEPrivateData\x00\x01\x01Bypass\x00")
        name, vals = compare.decode(comp)
        self.assertEqual(name, "JUCE ValueTree")
        self.assertEqual(vals["AppState@BPM"], 90.0)
        self.assertEqual(vals["AppState@Model"], "P-Bass")
        self.assertIs(vals["AppState@Muted"], True)
        self.assertEqual(vals["AppState/Child@Level"], -3.0)
        self.assertEqual(vals["AppState@AmpNode/AmpTubeState@Gain"], 0.5)
        self.assertNotIn("AppState@AmpNode#rest", vals)   # memory left after the tree, not a setting
        self.assertNotIn("AppState@GuiScale", vals)   # window size isn't a setting

    def test_value_tree_differences_are_found(self):
        a = _vst2_wrapped(_vt("AppState", {"BPM": 90.0, "Model": "P-Bass"}))
        b = _vst2_wrapped(_vt("AppState", {"BPM": 90.0, "Model": "J-Bass"}))
        A, B = compare.decode(a)[1], compare.decode(b)[1]
        self.assertIsNone(compare.same(A["AppState@Model"], B["AppState@Model"]))

    def test_juce_base64_round_trip(self):
        for data in (b"", b"\x00", b"hello world", bytes(range(256))):
            self.assertEqual(compare.juce_base64(_juce_b64(data)), data)
        self.assertIsNone(compare.juce_base64("not.base64!"))

    def test_older_version_bank_goes_in_under_the_current_wrapper(self):
        chunk = b"<State><Model Drawbar1='8.0'/></State>"
        old = _vst2_wrapped(chunk, version=0x10303)
        cur = _vst2_wrapped(b"<State/>", version=0x10305)
        got = formats._current_wrapper(old, cur)
        self.assertEqual(states.juce_split(got)[2], chunk)
        self.assertEqual(states.juce_split(got)[1][20:24], struct.pack(">I", 0x10305))
        # another plug-in's bank, or the same version: left exactly as the file has it
        self.assertEqual(formats._current_wrapper(_vst2_wrapped(chunk, 0x10303, b"Othr"), cur),
                         _vst2_wrapped(chunk, 0x10303, b"Othr"))
        same = _vst2_wrapped(chunk, version=0x10305)
        self.assertEqual(formats._current_wrapper(same, cur), same)
        self.assertEqual(formats._current_wrapper(b"not wrapped", cur), b"not wrapped")

    def test_windows_paths_and_build_numbers_are_not_differences(self):
        self.assertEqual(compare.same("Instruments\\50__Piano\\Grand.st3i", "Instruments/50__Piano/Grand.st3i"), "same")
        self.assertIsNone(compare.same("Instruments\\Grand.st3i", "Instruments/Upright.st3i"))
        xml = b"<Multi><BuildVersion>(%s)</BuildVersion><Gain>1</Gain></Multi>"
        a = _vst2_wrapped(_vt("State", {"Plugin": compare.states.vc2(xml % b"22L13")}))
        b = _vst2_wrapped(_vt("State", {"Plugin": compare.states.vc2(xml % b"25F27")}))
        self.assertEqual(compare.decode(a)[1], compare.decode(b)[1])

    def test_wording(self):
        words = pipeline.unscanned_words(["MODO DRUM"])
        self.assertIn("1 plug-in your REAPER hasn't scanned yet, so its presets", words)
        self.assertIn("File, Scan New Plug-ins", words)
        self.assertIn("rplmaker scan-new", pipeline.unscanned_words(["A", "B"], how="rplmaker scan-new"))
        done = pipeline.scan_new_words(["MODO DRUM"], ["Broken"])
        self.assertIn("Scanned MODO DRUM. Its presets are offered now; libraries made for it work", done)
        self.assertIn("scan it;", pipeline.unscanned_words(["MODO DRUM"]))
        self.assertIn("Broken didn't answer the checking copy, so it can't be offered yet", done)
