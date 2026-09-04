"""Tests for the animation engine.

It needs Qt for the QPixmaps, but runs headless: the `offscreen` platform is
forced before the QGuiApplication is created.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import zlib
import struct
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from src import states as st  # noqa: E402
from src.animation_engine import (  # noqa: E402
    AnimationEngine,
    available_characters,
)

# QApplication and not QGuiApplication: the window tests need to create
# QWidgets, and if the most basic type were instantiated here, they would blow
# up over there.
_app = QApplication.instance() or QApplication([])


def _png(path: Path) -> None:
    """A 2x2 RGBA PNG written by hand: the tests do not depend on the assets."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + b"\xff\x00\x00\xff" * 2 for _ in range(2))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


class BaseAssets(unittest.TestCase):
    """Builds fake characters with whatever states each test asks for."""

    def temp_folder(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def populate(self, root: Path, **states: int) -> Path:
        for state, count in states.items():
            folder = root / state
            folder.mkdir(parents=True, exist_ok=True)
            for i in range(count):
                _png(folder / f"frame_{i + 1:02d}.png")
        return root

    def make(self, **states: int) -> AnimationEngine:
        """Flat layout: `assets/<state>/`, with no character folder."""
        return AnimationEngine(self.populate(self.temp_folder(), **states))

    def make_with_characters(self, **characters: dict) -> AnimationEngine:
        """Current layout: `assets/<character>/<state>/`."""
        root = self.temp_folder()
        for name, data in characters.items():
            states = {k: v for k, v in data.items() if k != "sheet"}
            self.populate(root / name, **states)
            if "sheet" in data:
                import json

                (root / name / "character.json").write_text(
                    json.dumps(data["sheet"]), encoding="utf-8"
                )
        return AnimationEngine(root)


class TestResolution(BaseAssets):
    def test_it_uses_its_own_sprites_when_they_exist(self):
        e = self.make(idle=2, working=3)
        e.set_state(st.WORKING)
        self.assertEqual(e.resolved_state, st.WORKING)

    def test_it_inherits_from_the_parent(self):
        e = self.make(idle=2, working=3)
        e.set_state(st.WORKING_BASH)
        self.assertEqual(e.state, st.WORKING_BASH)
        self.assertEqual(e.resolved_state, st.WORKING)

    def test_it_inherits_from_the_grandparent(self):
        e = self.make(idle=2)
        e.set_state(st.WORKING_BASH)
        self.assertEqual(e.resolved_state, st.IDLE)

    def test_an_explicit_parent(self):
        e = self.make(idle=2, thinking=3)
        e.set_state(st.WAITING)
        self.assertEqual(e.resolved_state, st.THINKING)

    def test_every_state_yields_a_frame(self):
        e = self.make(idle=2)
        for state in st.STATES:
            e.set_state(state)
            self.assertIsNotNone(e.current_frame(), f"{state} has no frame")

    def test_with_no_assets_it_does_not_blow_up(self):
        e = self.make()
        e.set_state(st.WORKING)
        self.assertIsNone(e.current_frame())
        self.assertIsNone(e.advance())

    def test_inherited_siblings_do_not_restart_the_animation(self):
        # working-bash and working-edit, both undrawn, land on working:
        # switching between them must not jump back to the first frame.
        e = self.make(idle=2, working=4)
        e.set_state(st.WORKING_BASH)
        e.advance()
        e.advance()
        before = e._index
        e.set_state(st.WORKING_EDIT)
        self.assertEqual(e._index, before)


class TestLooping(BaseAssets):
    def test_ordinary_states_wrap_around(self):
        e = self.make(idle=3)
        self.assertFalse(e.plays_once())
        seen = [e._index]
        for _ in range(5):
            e.advance()
            seen.append(e._index)
        self.assertEqual(seen, [0, 1, 2, 0, 1, 2])


class TestOneShot(BaseAssets):
    def test_it_stops_on_the_last_frame(self):
        e = self.make(idle=2, done=3)
        e.set_state(st.DONE)
        self.assertTrue(e.plays_once())
        self.assertEqual(
            [e._index] + [(e.advance(), e._index)[1] for _ in range(4)],
            [0, 1, 2, 2, 2],
        )

    def test_finished_reports_reaching_the_end(self):
        e = self.make(idle=2, done=3)
        e.set_state(st.DONE)
        self.assertFalse(e.finished())
        e.advance()
        self.assertFalse(e.finished())
        e.advance()
        self.assertTrue(e.finished())

    def test_an_inherited_one_goes_back_to_looping(self):
        # `done` without its own sprites falls back to idle, which is a loop:
        # freezing it would look stuck.
        e = self.make(idle=3)
        e.set_state(st.DONE)
        self.assertFalse(e.plays_once())
        self.assertFalse(e.finished())
        for _ in range(3):
            e.advance()
        self.assertEqual(e._index, 0)

    def test_repeating_the_state_plays_it_again(self):
        e = self.make(idle=2, done=3)
        e.set_state(st.DONE)
        e.advance()
        e.advance()
        self.assertTrue(e.finished())
        e.set_state(st.DONE)  # a second Stop right after
        self.assertEqual(e._index, 0)
        self.assertFalse(e.finished())

    def test_the_one_shot_states_are_the_transients(self):
        self.assertEqual(set(st.ONE_SHOT), set(st.TRANSIENTS))


class TestDurations(BaseAssets):
    def test_the_duration_of_a_one_shot(self):
        e = self.make(idle=2, done=4)
        # done: 4 frames x 160 ms
        self.assertEqual(e.duration_ms(st.DONE), 4 * 160)

    def test_it_detects_a_cut_animation(self):
        # 40 done frames at 160 ms are 6.4 s, and done expires much earlier.
        e = self.make(idle=2, done=40)
        truncated = dict((s, ms) for s, ms, _ in e.truncated_states())
        self.assertIn(st.DONE, truncated)

    def test_it_says_nothing_when_it_fits(self):
        e = self.make(idle=2, done=4)
        self.assertEqual(e.truncated_states(), [])

    def test_it_says_nothing_about_inherited_states(self):
        e = self.make(idle=2)
        self.assertEqual(e.truncated_states(), [])

    def test_duration_ms_does_not_disturb_the_current_state(self):
        e = self.make(idle=2, done=4)
        e.set_state(st.THINKING)
        e.duration_ms(st.DONE)
        self.assertEqual(e.state, st.THINKING)


class TestReloading(BaseAssets):
    def test_reload_picks_up_new_sprites(self):
        e = self.make(idle=2)
        e.set_state(st.WORKING)
        self.assertEqual(e.resolved_state, st.IDLE)

        folder = e.assets_dir / st.WORKING
        folder.mkdir()
        for i in range(3):
            _png(folder / f"frame_{i + 1:02d}.png")

        e.reload()
        self.assertEqual(e.resolved_state, st.WORKING)
        self.assertIn(st.WORKING, e.available_states())


class TestCharacters(BaseAssets):
    def test_it_discovers_characters(self):
        e = self.make_with_characters(
            dragoncita={"idle": 2}, cat={"idle": 2, "thinking": 3}
        )
        self.assertEqual(e.characters(), ["cat", "dragoncita"])

    def test_it_uses_the_first_one_by_default(self):
        e = self.make_with_characters(aaa={"idle": 2}, zzz={"idle": 3})
        self.assertEqual(e.character, "aaa")

    def test_switching_character_reloads(self):
        # They are sorted alphabetically, so it starts on "aaa".
        e = self.make_with_characters(
            aaa={"idle": 2}, bbb={"idle": 2, "working": 4}
        )
        self.assertEqual(e.character, "aaa")
        self.assertNotIn(st.WORKING, e.available_states())
        e.set_character("bbb")
        self.assertIn(st.WORKING, e.available_states())

    def test_the_flat_layout_still_works(self):
        # Someone who cloned an earlier version has assets/<state>/.
        e = self.make(idle=2, working=3)
        self.assertIsNone(e.character)
        self.assertIn(st.WORKING, e.available_states())

    def test_the_name_from_the_sheet(self):
        e = self.make_with_characters(
            dragoncita={"idle": 2, "sheet": {"name": "Dragoncita"}}
        )
        self.assertEqual(e.character_name, "Dragoncita")

    def test_with_no_sheet_it_uses_the_folder_name(self):
        e = self.make_with_characters(cat={"idle": 2})
        self.assertEqual(e.character_name, "cat")

    def test_an_empty_folder_is_not_a_character(self):
        root = self.temp_folder()
        (root / "not_a_character").mkdir()
        self.assertEqual(available_characters(root), [])


class TestFrozen(BaseAssets):
    """The warning that a final pose is being held for too long."""

    def test_an_animation_too_short_for_its_expiry_warns(self):
        # `done` expires at 1.3 s; with 1 frame the animation lasts a blink.
        e = self.make(idle=2, done=1)
        states = [s for s, _, _ in e.frozen_states()]
        self.assertIn(st.DONE, states)

    def test_a_well_calibrated_animation_does_not_warn(self):
        # Enough frames to fill most of the expiry.
        e = self.make(idle=2, done=8)
        self.assertNotIn(st.DONE, [s for s, _, _ in e.frozen_states()])

    def test_inherited_states_do_not_count(self):
        # With no sprites of its own it loops: there is nothing to freeze.
        e = self.make(idle=2)
        self.assertEqual(e.frozen_states(), [])

    def test_it_reports_how_much_is_left_over(self):
        e = self.make(idle=2, done=1)
        _state, spare, limit = next(
            t for t in e.frozen_states() if t[0] == st.DONE
        )
        self.assertGreater(spare, 0)
        self.assertAlmostEqual(limit, st.TRANSIENTS[st.DONE][0])


class TestSheet(BaseAssets):
    def test_the_scale_from_the_sheet(self):
        e = self.make_with_characters(x={"idle": 2, "sheet": {"scale": 3}})
        self.assertEqual(e.scale, 3)

    def test_the_default_scale(self):
        e = self.make_with_characters(x={"idle": 2})
        self.assertEqual(e.scale, 2)

    def test_an_invalid_scale_does_not_blow_up(self):
        e = self.make_with_characters(x={"idle": 2, "sheet": {"scale": "big"}})
        self.assertEqual(e.scale, 2)

    def test_the_scale_is_never_zero(self):
        e = self.make_with_characters(x={"idle": 2, "sheet": {"scale": 0}})
        self.assertEqual(e.scale, 1)

    def test_the_speeds_from_the_sheet(self):
        e = self.make_with_characters(
            x={"idle": 2, "sheet": {"ms_per_frame": {"idle": 999}}}
        )
        self.assertEqual(e.interval_ms(st.IDLE), 999)

    def test_a_speed_inherited_from_an_ancestor(self):
        e = self.make_with_characters(
            x={"idle": 2, "working": 3,
               "sheet": {"ms_per_frame": {"working": 55}}}
        )
        self.assertEqual(e.interval_ms(st.WORKING_BASH), 55)

    def test_a_broken_sheet_does_not_blow_up(self):
        e = self.make_with_characters(x={"idle": 2})
        (e.assets_dir / "x" / "character.json").write_text(
            "{ broken", encoding="utf-8"
        )
        e.reload()
        self.assertEqual(e.scale, 2)
        self.assertIn(st.IDLE, e.available_states())

    def test_the_canvas_is_read_from_the_sprites(self):
        e = self.make_with_characters(x={"idle": 2, "sheet": {"scale": 4}})
        self.assertEqual(e.frame_px, 2)  # the test PNGs are 2x2
        self.assertEqual(e.canvas_px, 8)


class TestEntryPlusLoop(BaseAssets):
    """Animations with an opening that plays once and a tail that repeats.

    Dragging the avatar is the first one: it lifts, and then sways for as long
    as you hold it. Which frame the tail starts at is a property of the
    drawing, so it lives in the character's sheet next to the speeds and not in
    the state table — another character may draw the same state differently.
    """

    def sequence(self, engine, steps: int) -> list[int]:
        """Frame numbers as they go on screen, counted like the file names."""
        seen = [engine._index + 1]
        for _ in range(steps):
            engine.advance()
            seen.append(engine._index + 1)
        return seen

    def test_the_opening_plays_once_and_the_tail_repeats(self):
        e = self.make_with_characters(
            x={"dragged": 7, "sheet": {"loop_from": {"dragged": 6}}})
        e.set_state(st.DRAGGED)
        self.assertEqual(self.sequence(e, 10),
                         [1, 2, 3, 4, 5, 6, 7, 6, 7, 6, 7])

    def test_without_a_loop_point_it_still_starts_over(self):
        e = self.make_with_characters(x={"dragged": 4})
        e.set_state(st.DRAGGED)
        self.assertEqual(self.sequence(e, 5), [1, 2, 3, 4, 1, 2])

    def test_a_one_shot_still_freezes(self):
        e = self.make_with_characters(x={"done": 3})
        e.set_state(st.DONE)
        self.assertEqual(self.sequence(e, 4), [1, 2, 3, 3, 3])

    def test_a_tail_keeps_even_a_one_shot_moving(self):
        # `done` freezes on its last frame until the state expires. With a tail
        # declared it sways there instead of sitting still: the rule is about
        # the shape of the drawing, not about the kind of state.
        e = self.make_with_characters(
            x={"done": 4, "sheet": {"loop_from": {"done": 3}}})
        e.set_state(st.DONE)
        self.assertEqual(self.sequence(e, 5), [1, 2, 3, 4, 3, 4])

    def test_a_number_out_of_range_is_ignored(self):
        # Clamping would park the avatar on a frame nobody chose. Falling back
        # to looping from the start is what it did before the feature existed.
        for bad in (0, 9, -3, "six", None):
            with self.subTest(loop_from=bad):
                e = self.make_with_characters(
                    x={"dragged": 4, "sheet": {"loop_from": {"dragged": bad}}})
                e.set_state(st.DRAGGED)
                self.assertEqual(self.sequence(e, 4), [1, 2, 3, 4, 1])

    def test_a_broken_loop_table_leaves_the_rest_of_the_sheet_alone(self):
        # One entry going wrong has no business taking the sheet down with it.
        e = self.make_with_characters(
            x={"idle": 2, "sheet": {"loop_from": "not a table",
                                    "ms_per_frame": {"idle": 999}}})
        self.assertEqual(e.interval_ms(), 999)

    def test_the_drawn_dragoncita_sways_while_you_carry_her(self):
        """The real character, not a fixture: the sheet and the folder agree.

        Nothing else would notice if they stopped agreeing — a wrong number
        just loops from somewhere else, which looks like a drawing decision.
        """
        e = AnimationEngine(ROOT / "assets")
        e.set_state(st.DRAGGED)
        self.assertEqual(e.state, e._resolved, "dragged has no sprites of its own")
        self.assertEqual(self.sequence(e, 9),
                         [1, 2, 3, 4, 5, 6, 7, 6, 7, 6])


if __name__ == "__main__":
    unittest.main(verbosity=2)
