"""Tests for the shape of the entrance: a real fall, then one small hop."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import entrance as en  # noqa: E402

DISTANCE, HOP = 1000.0, 16.0


def height(ms: float) -> float:
    return en.height_at(ms, DISTANCE, HOP)


class TestTheFall(unittest.TestCase):
    def test_it_starts_up_there(self):
        self.assertEqual(height(0), DISTANCE)

    def test_it_speeds_up(self):
        # Gravity, not a constant glide: each slice of time covers more
        # ground than the one before.
        landing = en.fall_ms(DISTANCE)
        slices = [height(landing * i / 4) for i in range(5)]
        drops = [a - b for a, b in zip(slices, slices[1:])]
        self.assertEqual(drops, sorted(drops))
        self.assertGreater(drops[-1], drops[0] * 3)

    def test_it_touches_down_on_its_spot(self):
        self.assertAlmostEqual(height(en.fall_ms(DISTANCE)), 0.0, places=6)

    def test_a_full_screen_does_not_keep_you_waiting(self):
        self.assertLess(en.fall_ms(1080), 800)
        self.assertGreater(en.fall_ms(1080), 400)

    def test_twice_the_height_is_not_twice_the_wait(self):
        # Why the duration follows the distance: a real fall grows with its
        # square root, so a taller screen does not feel sluggish.
        self.assertAlmostEqual(en.fall_ms(2000) / en.fall_ms(500), 2.0)


class TestTheHop(unittest.TestCase):
    def landing(self) -> float:
        return en.fall_ms(DISTANCE)

    def test_it_goes_back_up_exactly_that_high(self):
        peak = height(self.landing() + en.hop_ms(HOP) / 2)
        self.assertAlmostEqual(peak, HOP, places=6)

    def test_it_never_dips_below_the_floor(self):
        total = self.landing() + en.hop_ms(HOP)
        for i in range(101):
            self.assertGreaterEqual(height(total * i / 100), 0.0)

    def test_it_stays_put_once_over(self):
        end = self.landing() + en.hop_ms(HOP)
        self.assertEqual(height(end), 0.0)
        self.assertEqual(height(end + 5000), 0.0)

    def test_it_is_small(self):
        # One hop, a fraction of the avatar: a landing, not a bouncing ball.
        self.assertLess(en.HOP_SHARE, 0.15)


if __name__ == "__main__":
    unittest.main(verbosity=2)
