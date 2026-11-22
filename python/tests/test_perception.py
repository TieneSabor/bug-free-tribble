"""Perception lifecycle and attribution tests."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PYDIR = os.path.dirname(HERE)
if PYDIR not in sys.path:
    sys.path.insert(0, PYDIR)

from tests import support  # noqa: E402
from mechbot.perception.tracking import Perception  # noqa: E402


class FakeMap:
    def __init__(self, clear: bool = True):
        self.clear = clear

    def los(self, a, b) -> bool:
        return self.clear

    def shot_clear(self, a, b) -> bool:
        return self.clear


class TestPerception(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = support.load_config()
        self.p = Perception(self.cfg, FakeMap())

    def test_visible_and_lost(self) -> None:
        bf = self.p.update(support.make_obs(t=0.0, mechs=[support.make_mech(5, 10.0, 0.0)]))
        tr = bf.track(5)
        self.assertIsNotNone(tr)
        self.assertEqual(tr.status, "visible")
        self.assertTrue(bf.targetable(tr))

        bf = self.p.update(support.make_obs(t=0.6, mechs=[]))
        tr = bf.track(5)
        self.assertIsNotNone(tr)
        self.assertEqual(tr.status, "lost")
        self.assertFalse(bf.targetable(tr))

    def test_remembered_when_los_fails(self) -> None:
        self.p = Perception(self.cfg, FakeMap(clear=False))
        bf = self.p.update(support.make_obs(t=0.0, mechs=[support.make_mech(5, 10.0, 0.0)]))
        tr = bf.track(5)
        self.assertEqual(tr.status, "remembered")
        self.assertFalse(bf.targetable(tr))

    def test_damage_attribution(self) -> None:
        ev = {
            "type": "damaged",
            "amount": 45,
            "weapon": "gun",
            "bearing": 0.0,
            "by": 5,
        }
        bf = self.p.update(
            support.make_obs(t=0.0, mechs=[support.make_mech(5, 20.0, 0.0)], events=[ev])
        )
        tr = bf.track(5)
        self.assertIsNotNone(tr)
        self.assertEqual(tr.last_damaged_us_t, 0.0)
        self.assertAlmostEqual(bf.last_damage_bearing(2.0), 0.0)
        self.assertEqual(bf.attacker_since(3.0).id, 5)


if __name__ == "__main__":
    unittest.main()
