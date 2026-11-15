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
