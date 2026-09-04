"""Tests for the persistent preferences.

`config.py` is plain Python: tested without Qt and without touching the user's
disk.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import Config  # noqa: E402


class BaseConfig(unittest.TestCase):
    def path(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name) / "config.json"


class TestDefaults(BaseConfig):
    def test_a_missing_file_does_not_blow_up(self):
        c = Config(self.path()).load()
        self.assertIsNone(c.position)
        self.assertIsNone(c.character)

    def test_broken_json_falls_back_to_defaults(self):
        p = self.path()
        p.write_text("{ this is not json", encoding="utf-8")
        c = Config(p).load()
        self.assertIsNone(c.position)
        self.assertIsNone(c.character)

    def test_a_file_with_a_bom_still_reads(self):
        # Notepad and PowerShell save with a BOM. Opening the file just to look
        # at it should not wipe the preferences.
        p = self.path()
        p.write_bytes(b"\xef\xbb\xbf" + b'{"position": [7, 8]}')
        self.assertEqual(Config(p).load().position, (7, 8))

    def test_json_that_is_not_an_object(self):
        p = self.path()
        p.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertIsNone(Config(p).load().position)


class TestRoundTrip(BaseConfig):
    def test_it_survives_between_instances(self):
        p = self.path()
        a = Config(p).load()
        a.position = (120, 340)
        a.character = "dragoncita"
        self.assertTrue(a.save())

        b = Config(p).load()
        self.assertEqual(b.position, (120, 340))
        self.assertEqual(b.character, "dragoncita")

    def test_the_file_is_readable_json(self):
        p = self.path()
        c = Config(p).load()
        c.position = (1, 2)
        c.save()
        data = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(data["position"], [1, 2])

    def test_saving_leaves_no_temporary_files(self):
        p = self.path()
        c = Config(p).load()
        c.position = (5, 5)
        c.save()
        leftovers = [f.name for f in p.parent.iterdir() if f.name != p.name]
        self.assertEqual(leftovers, [], f"files left behind: {leftovers}")

    def test_saving_is_atomic(self):
        # If a save were cut in half, the previous file must still be valid
        # rather than truncated.
        p = self.path()
        c = Config(p).load()
        c.position = (1, 1)
        c.save()
        first = p.read_text(encoding="utf-8")
        c.position = (2, 2)
        c.save()
        self.assertNotEqual(p.read_text(encoding="utf-8"), first)
        json.loads(p.read_text(encoding="utf-8"))  # still valid json


class TestValidation(BaseConfig):
    def test_junk_positions_are_ignored(self):
        for junk in ('"there"', "[1]", "[1,2,3]", '["a","b"]', "null", "42"):
            p = self.path()
            p.write_text(f'{{"position": {junk}}}', encoding="utf-8")
            self.assertIsNone(
                Config(p).load().position, f"{junk} was not ignored"
            )

    def test_a_fractional_position_is_truncated(self):
        p = self.path()
        p.write_text('{"position": [10.7, 20.2]}', encoding="utf-8")
        self.assertEqual(Config(p).load().position, (10, 20))

    def test_an_empty_character_is_none(self):
        p = self.path()
        p.write_text('{"character": ""}', encoding="utf-8")
        self.assertIsNone(Config(p).load().character)

    def test_a_character_that_is_not_text(self):
        p = self.path()
        p.write_text('{"character": 42}', encoding="utf-8")
        self.assertIsNone(Config(p).load().character)

    def test_a_preference_can_be_cleared(self):
        p = self.path()
        c = Config(p).load()
        c.position = (1, 2)
        c.character = "x"
        c.save()
        c.position = None
        c.character = None
        c.save()
        back = Config(p).load()
        self.assertIsNone(back.position)
        self.assertIsNone(back.character)


class TestPort(BaseConfig):
    """It exists for when another program already holds 8770."""

    def write(self, value) -> Config:
        p = self.path()
        p.write_text(json.dumps({"port": value}), encoding="utf-8")
        return Config(p).load()

    def test_no_port_returns_none(self):
        # `None` means "use the usual one", not "error".
        self.assertIsNone(Config(self.path()).load().port)

    def test_a_valid_port(self):
        self.assertEqual(self.write(8771).port, 8771)

    def test_a_port_as_text_works_too(self):
        # Edited by hand, it easily ends up quoted.
        self.assertEqual(self.write("8771").port, 8771)

    def test_a_junk_port_is_ignored(self):
        self.assertIsNone(self.write("eight thousand").port)

    def test_the_widget_can_record_the_port_it_picked(self):
        # When the preferred one is taken by another program the widget moves
        # and records where to: `hooks/notify.py` reads this same file, and if
        # only one of the two changed, the events would go to the old port.
        p = self.path()
        c = Config(p).load()
        c.port = 8771
        self.assertTrue(c.save())
        self.assertEqual(Config(p).load().port, 8771)

    def test_an_out_of_range_port_is_ignored(self):
        # An impossible port would leave the widget unable to start, with no
        # explanation.
        self.assertIsNone(self.write(99999).port)
        self.assertIsNone(self.write(80).port)  # reserved
        self.assertIsNone(self.write(-1).port)


class TestWriteFailures(BaseConfig):
    def test_a_missing_folder_is_created(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = Path(tmp.name) / "sub" / "folder" / "config.json"
        c = Config(p).load()
        c.position = (3, 4)
        self.assertTrue(c.save())
        self.assertEqual(Config(p).load().position, (3, 4))

    def test_being_unable_to_save_does_not_blow_up(self):
        # An impossible path: the "directory" is actually a file.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        a_file = Path(tmp.name) / "i_am_a_file"
        a_file.write_text("x", encoding="utf-8")
        c = Config(a_file / "config.json").load()
        c.position = (1, 1)
        self.assertFalse(c.save())  # returns False, does not raise


if __name__ == "__main__":
    unittest.main(verbosity=2)
