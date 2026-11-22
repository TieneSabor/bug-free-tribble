"""Zone substate trigger/recovery tests with a synthetic nav and battlefield."""
from __future__ import annotations

import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PYDIR = os.path.dirname(HERE)
if PYDIR not in sys.path:
    sys.path.insert(0, PYDIR)

from tests import support  # noqa: E402
from mechbot.decision.modes.zone import ZoneMode  # noqa: E402


class FakeNav:
    def nearest_walkable(self, x, y, max_rings=10):
        return x, y

    def is_walkable(self, x, y):
        return True

    def path_cached(self, start, goal, force=False):
        return [(float(goal[0]), float(goal[1]))]

    def line_clear(self, x, y, dx, dy, dist, step=3.0):
        return True

    def local_clear(self, x, y, dx, dy, dist):
        return True


class FakeBF:
    def __init__(self, t, me, zone):
        self.t = t
        self.me = me
        self.zone = zone

    def last_damage_bearing(self, max_age_s=2.0):
        return None


class TestZoneMode(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = support.load_config()
        self.nav = FakeNav()

    def test_move_latches_when_outside_next(self) -> None:
        me = support.make_me(0.0, 0.0)
        me["in_zone"] = True
        zone = support.make_zone(
            t=0.0,
            center=[0.0, 0.0],
            radius=560.0,
            next_center=[200.0, 0.0],
            next_radius=50.0,
            shrink_start=10.0,
            shrink_end=50.0,
        )
        bf = FakeBF(0.0, me, zone)
        z = ZoneMode(self.cfg, self.nav)
        z.tick(bf)
        self.assertTrue(z.move_latched)
        self.assertEqual(z.priority(bf), 30)
        intent = z.update(bf)
        self.assertTrue(intent.label.startswith("zone:move"))
        self.assertGreater(abs(intent.move[0]) + abs(intent.move[1]), 0.0)

    def test_hold_when_already_safe(self) -> None:
        me = support.make_me(0.0, 0.0)
        me["in_zone"] = True
        zone = support.make_zone(
            t=0.0,
            center=[0.0, 0.0],
            radius=560.0,
            next_center=[0.0, 0.0],
            next_radius=380.0,
            shrink_start=60.0,
            shrink_end=110.0,
        )
        bf = FakeBF(0.0, me, zone)
        z = ZoneMode(self.cfg, self.nav)
        z.tick(bf)
        self.assertFalse(z.move_latched)
        self.assertEqual(z.priority(bf), 10)
        self.assertTrue(z.update(bf).label.startswith("zone:hold"))

    def test_recovery_until_inside_next(self) -> None:
        me = support.make_me(600.0, 0.0)
        me["in_zone"] = False
        zone = support.make_zone(
            t=0.0,
            center=[0.0, 0.0],
            radius=560.0,
            next_center=[0.0, 0.0],
            next_radius=380.0,
            shrink_start=60.0,
            shrink_end=110.0,
            dps=100.0,
        )
        bf = FakeBF(0.0, me, zone)
        z = ZoneMode(self.cfg, self.nav)
        z.tick(bf)
        self.assertTrue(z.recovery)
        self.assertEqual(z.priority(bf), 40)
        self.assertTrue(z.update(bf).label.startswith("zone:recovery"))

        me["pos"] = [0.0, 0.0, 0.0]
        me["in_zone"] = True
        bf.t = 1.0
        z.tick(bf)
        self.assertFalse(z.recovery)


if __name__ == "__main__":
    unittest.main()
