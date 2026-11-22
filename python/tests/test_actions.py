"""Action assembly tests."""
from __future__ import annotations

import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PYDIR = os.path.dirname(HERE)
if PYDIR not in sys.path:
    sys.path.insert(0, PYDIR)

from tests import support  # noqa: E402
from mechbot.action.builder import ActionBuilder  # noqa: E402
from mechbot.action.intent import Intent  # noqa: E402


class TestActionBuilder(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = support.load_config()
        self.b = ActionBuilder(self.cfg)

    def test_clamps_and_fire_slots(self) -> None:
        obs = support.make_obs()
        obs["self"]["weapons"] = [obs["self"]["weapons"][0], None]
        act = self.b.build(
            Intent(move=(2.0, 2.0), aim=(10.0, -10.0), fire=(True, True), label="x"), obs
        )
        self.assertAlmostEqual(math.hypot(*act["move"]), 1.0, places=6)
        self.assertEqual(act["tick"], obs["tick"])
        self.assertAlmostEqual(act["aim"][1], self.cfg.min_pitch)
        self.assertEqual(act["fire"], [True, False])

    def test_fractional_move_is_preserved(self) -> None:
        obs = support.make_obs()
        act = self.b.build(Intent(move=(0.35, 0.0)), obs)
        self.assertAlmostEqual(act["move"][0], 0.35, places=6)

    def test_offer_pick(self) -> None:
        obs = support.make_obs()
        obs["offer"] = {"id": 1, "choices": [{"id": "a", "name": "A", "desc": ""}], "expires": 5.0}
        act = self.b.build(Intent(), obs)
        self.assertEqual(act.get("pick"), 0)

    def test_empty_weapon_does_not_fire(self) -> None:
        obs = support.make_obs()
        obs["self"]["weapons"] = [None, None]
        act = self.b.build(Intent(fire=(True, True)), obs)
        self.assertEqual(act["fire"], [False, False])

    def test_fallback_tick(self) -> None:
        obs = support.make_obs(tick=42)
        act = self.b.fallback(obs)
        self.assertEqual(act["tick"], 42)
        self.assertEqual(act["fire"], [False, False])


if __name__ == "__main__":
    unittest.main()
