"""Arm 3 economy: drones as candidates, crate shooting, drop alone-ness."""
from __future__ import annotations

import math
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PYDIR = os.path.dirname(HERE)
if PYDIR not in sys.path:
    sys.path.insert(0, PYDIR)

from tests import support  # noqa: E402
from mechbot import tuning  # noqa: E402
from mechbot.decision.arbiter import Arbiter  # noqa: E402
from mechbot.decision.loot import LootChooser  # noqa: E402
from mechbot.perception.items import DROP, ItemMemory  # noqa: E402
from mechbot.perception.model import AgentTrack  # noqa: E402


class FakeField:
    eta = [0.0]

    def deadline(self, zone, pos, now, margin=8.0):
        return 1e9


class FakeBF:
    def __init__(self, me, zone, items, tracks=(), contacts=()):
        self.me = me
        self.zone = zone
        self.items = items
        self.tracks = {t.id: t for t in tracks}
        self.contacts = list(contacts)
        self.t = 0.0
        self.alive = 16
        self.last_damage_t = -1e9

    def last_damage_bearing(self, max_age_s=2.0):
        return None


def npc(ident=104, x=40.0, y=0.0, hp=350.0):
    t = AgentTrack(id=ident, kind="npc", pos=(x, y, 0.0), vel=(0.0, 0.0, 0.0),
                   hp=hp, max_hp=350.0, weapons=())
    t.status = "visible"
    t.last_listed_t = 0.0
    t.last_visible_t = 0.0
    return t


def mech(ident=5, x=15.0, y=0.0):
    t = AgentTrack(id=ident, kind="mech", pos=(x, y, 0.0), vel=(0.0, 0.0, 0.0),
                   aim=(0.0, 0.0), hp=1400.0, max_hp=1400.0, weapons=("gun",))
    t.status = "visible"
    t.last_listed_t = 0.0
    t.last_visible_t = 0.0
    return t


class TestDrones(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = support.load_config()
        self.mem = ItemMemory(self.cfg)
        self.zone = support.make_zone(t=0.0)
        self.chooser = LootChooser(self.cfg)

    def test_drone_is_a_candidate_even_without_items(self) -> None:
        bf = FakeBF(support.make_me(hp=1400.0), self.zone, self.mem, [npc()])
        pick = self.chooser.select(bf, FakeField(), 5.0)
        self.assertIsNotNone(pick)
        self.assertEqual(pick.kind, "drone")
        self.assertEqual(pick.id, 104)

    def test_drone_ignored_when_hurt(self) -> None:
        bf = FakeBF(support.make_me(hp=700.0), self.zone, self.mem, [npc()])
        self.assertIsNone(self.chooser.select(bf, FakeField(), 5.0))

    def test_drone_out_of_range(self) -> None:
        bf = FakeBF(support.make_me(), self.zone, self.mem, [npc(x=200.0)])
        self.assertIsNone(self.chooser.select(bf, FakeField(), 5.0))

    def test_drone_near_a_mech_is_vetoed_by_threat(self) -> None:
        # a laser carrier that can see the drone site outguns us: no trip
        gunner = mech(x=45.0)
        gunner.weapons = ("laser",)
        bf = FakeBF(support.make_me(), self.zone, self.mem, [npc(x=40.0), gunner])
        self.assertIsNone(self.chooser.select(bf, FakeField(), 5.0))


class TestDropVeto(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = support.load_config()
        self.mem = ItemMemory(self.cfg)
        self.zone = support.make_zone(t=0.0)
        self.chooser = LootChooser(self.cfg)
        self.mem.items[20000] = _drop_item(now=0.0)

    def test_drop_without_company_is_taken(self) -> None:
        bf = FakeBF(support.make_me(), self.zone, self.mem, [])
        pick = self.chooser.select(bf, FakeField(), 5.0)
        self.assertIsNotNone(pick)
        self.assertEqual(pick.kind, DROP)

    def test_drop_with_a_mech_in_the_ring_is_skipped(self) -> None:
        bf = FakeBF(support.make_me(), self.zone, self.mem, [mech(x=60.0)])
        # the mech sits 20 m from the drop at (75, 0)
        bf.tracks[5].pos = (75.0 + 10.0, 0.0, 0.0)
        self.assertIsNone(self.chooser.select(bf, FakeField(), 5.0))


def _drop_item(now=0.0):
    from mechbot.perception.items import Item
    return Item(20000, DROP, (75.0, 0.0, 0.0), now, now, lands_in=0.0, radius=8.0)


class FakeLos:
    def shot(self, a, b):
        return False          # clear line to the crate

    def sight(self, a, b):
        return True


class FakeCombat:
    def face(self, bf, yaw):
        return (yaw, 0.0)


class TestCrateAim(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = support.load_config()
        self.arb = Arbiter(self.cfg, None, None, None, FakeCombat(), FakeLos(),
                           random.Random(1))

    def test_aims_at_a_crate_in_range(self) -> None:
        bf = FakeBF(support.make_me(x=0.0, y=0.0), support.make_zone(), None)
        aim = self.arb._crate_aim(bf, (25.0, 0.0, 0.0))
        self.assertIsNotNone(aim)
        self.assertAlmostEqual(aim[0], 0.0, places=3)

    def test_no_aim_out_of_range(self) -> None:
        bf = FakeBF(support.make_me(x=0.0, y=0.0), support.make_zone(), None)
        self.assertIsNone(self.arb._crate_aim(bf, (tuning.CRATE_RANGE_M + 20.0, 0.0, 0.0)))

    def test_no_aim_while_reloading(self) -> None:
        me = support.make_me(x=0.0, y=0.0)
        me["weapons"][0]["reload"] = 1.0
        bf = FakeBF(me, support.make_zone(), None)
        self.assertIsNone(self.arb._crate_aim(bf, (25.0, 0.0, 0.0)))

    def test_no_aim_with_empty_magazine(self) -> None:
        me = support.make_me(x=0.0, y=0.0, ammo=0)
        bf = FakeBF(me, support.make_zone(), None)
        self.assertIsNone(self.arb._crate_aim(bf, (25.0, 0.0, 0.0)))


class TestCubeValue(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = support.load_config()
        self.chooser = LootChooser(self.cfg)

    def test_threshold_cube_is_worth_more(self) -> None:
        # 2 -> 3 crosses a threshold; 4-5 stays between thresholds
        at_two = self.chooser._cube_value(2, 1.0)
        at_four = self.chooser._cube_value(4, 1.0)
        self.assertGreater(at_two, at_four)

    def test_low_hp_makes_a_cube_a_heal(self) -> None:
        self.assertGreater(self.chooser._cube_value(4, 0.3),
                           self.chooser._cube_value(4, 1.0))


if __name__ == "__main__":
    unittest.main()
