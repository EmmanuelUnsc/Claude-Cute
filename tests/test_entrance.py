"""Tests for the shape of the entrance: a meteor diving at 45 degrees."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import entrance as en  # noqa: E402

DISTANCE = 1000.0


def height(ms: float) -> float:
    return en.height_at(ms, DISTANCE)


class TestTheDive(unittest.TestCase):
    def test_it_starts_up_there(self):
        self.assertEqual(height(0), DISTANCE)

    def test_it_speeds_up(self):
        # Falling, not gliding: each slice of time covers more ground than the
        # one before.
        impact = en.fall_ms(DISTANCE)
        slices = [height(impact * i / 4) for i in range(5)]
        drops = [a - b for a, b in zip(slices, slices[1:])]
        self.assertEqual(drops, sorted(drops))
        self.assertGreater(drops[-1], drops[0] * 3)

    def test_it_hits_its_spot(self):
        self.assertAlmostEqual(height(en.fall_ms(DISTANCE)), 0.0, places=6)

    def test_it_stays_down_after_impact(self):
        # No bounce: what happens on the ground is the landing animation.
        end = en.fall_ms(DISTANCE)
        for extra in (1, 100, 5000):
            self.assertEqual(height(end + extra), 0.0)

    def test_a_full_screen_does_not_keep_you_waiting(self):
        self.assertLess(en.fall_ms(1080), 800)
        self.assertGreater(en.fall_ms(1080), 400)

    def test_twice_the_height_is_not_twice_the_wait(self):
        # A real fall grows with the square root, so a taller screen does not
        # feel sluggish.
        self.assertAlmostEqual(en.fall_ms(2000) / en.fall_ms(500), 2.0)

    def test_the_angle_matches_the_drawing(self):
        # The trail in `falling/` is drawn at 45 degrees.
        self.assertEqual(en.SLANT, 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
