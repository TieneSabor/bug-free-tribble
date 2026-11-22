"""Upgrade policy: the choice is valued, not defaulted."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PYDIR = os.path.dirname(HERE)
if PYDIR not in sys.path:
    sys.path.insert(0, PYDIR)

from tests import support  # noqa: E402
from mechbot.decision.upgrades import (  # noqa: E402
    UpgradePolicy,
    decision_interval,
    shots_per_s,
)


def offer(*ids):
    return {"id": 1, "expires": 9.0,
            "choices": [{"id": i, "name": i, "desc": ""} for i in ids]}


class TestUpgradePolicy(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = support.load_config()
        self.pol = UpgradePolicy(self.cfg)
        self.me = support.make_me()

    def test_decision_grid_quantises_gun_cooldown(self) -> None:
        self.assertAlmostEqual(decision_interval(0.24), 0.3)
        self.assertAlmostEqual(decision_interval(0.209), 0.3)
        self.assertAlmostEqual(decision_interval(0.181), 0.2)
        self.assertAlmostEqual(shots_per_s(0.181) / shots_per_s(0.24), 1.5)

    def test_one_gun_rate_stack_is_worthless(self) -> None:
        rate = self.pol.defs["gun_rate"]
        dmg = self.pol.defs["gun_damage"]
        self.assertAlmostEqual(self.pol.score(rate, self.me), 0.0)
        self.assertGreater(self.pol.score(dmg, self.me), 1.0)

    def test_two_gun_rate_stacks_are_worth_something(self) -> None:
        cd = float(self.cfg.weapon("gun")["cooldown"])
        once = cd * 0.87
        twice = cd * 0.87 * 0.87
        self.assertAlmostEqual(decision_interval(once), 0.3)
        self.assertAlmostEqual(decision_interval(twice), 0.2)

    def test_plating_beats_sensors(self) -> None:
        self.assertEqual(self.pol.choose(offer("sensors", "plating"), self.me), 1)

    def test_armor_has_increasing_returns(self) -> None:
        armor = self.pol.defs["armor"]
        first = self.pol.score(armor, self.me)
        me2 = dict(self.me)
        me2["stats"] = dict(self.me["stats"])
        me2["stats"]["armor"] = 0.16
        third = self.pol.score(armor, me2)
        self.assertGreater(third, first)

    def test_nanites_are_valuable(self) -> None:
        self.assertGreater(self.pol.score(self.pol.defs["nanites"], self.me), 100.0)

    def test_weapon_upgrade_needs_the_weapon(self) -> None:
        laser = self.pol.defs["laser_damage"]
        self.assertEqual(self.pol.score(laser, self.me), 0.0)
        me2 = dict(self.me)
        me2["weapons"] = [self.me["weapons"][0], {"kind": "laser", "stats": {}}]
        self.assertGreater(self.pol.score(laser, me2), 0.0)

    def test_no_offer_returns_none(self) -> None:
        self.assertIsNone(self.pol.choose(None, self.me))
        self.assertIsNone(self.pol.choose({"choices": []}, self.me))

    def test_unknown_choice_is_index_zero(self) -> None:
        self.assertEqual(self.pol.choose(offer("nope", "also_nope"), self.me), 0)

    def test_offer_always_answered(self) -> None:
        self.assertIn(self.pol.choose(offer("plating", "armor", "servos"), self.me), (0, 1, 2))


if __name__ == "__main__":
    unittest.main()
