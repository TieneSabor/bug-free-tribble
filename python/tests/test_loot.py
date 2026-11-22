"""Loot ranking: reachability, arrival race and local opposition."""
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
from mechbot.decision.loot import LootChooser  # noqa: E402
from mechbot.perception.items import PICKUP, Item, ItemMemory  # noqa: E402
from mechbot.perception.model import AgentTrack  # noqa: E402


class FakeField:
    def __init__(self, deadline: float = 1e9, eta=None):
        self._dl = deadline
        self.eta = eta if eta is not None else [0.0]

    def deadline(self, zone, pos, now, margin=8.0):
        return self._dl

    def eta_at(self, x, y):
        return 0.0


class FakeBF:
    def __init__(self, me, zone, items, tracks=(), field=None):
        self.me = me
        self.zone = zone
        self.items = items
        self.tracks = {t.id: t for t in tracks}
        self.field = field or FakeField()


def item(ident=8001, kind=PICKUP, x=100.0, y=0.0, detail="laser", t=0.0):
    return Item(ident, kind, (x, y, 0.0), t, t, detail=detail)


def track(ident, x, y, vel=(0.0, 0.0, 0.0), weapons=("gun",), hp=1400.0,
          aim=(0.0, 0.0)):
    t = AgentTrack(id=ident, kind="mech", pos=(x, y, 0.0), vel=vel, aim=aim,
                   hp=hp, max_hp=1400.0, weapons=tuple(weapons))
    t.status = "visible"
    t.last_listed_t = 0.0
    t.last_visible_t = 0.0
    return t


class TestLootChoice(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = support.load_config()
        self.me = support.make_me(x=0.0, y=0.0)
        self.zone = support.make_zone(t=0.0)
        self.mem = ItemMemory(self.cfg)
        self.chooser = LootChooser(self.cfg)

    def _bf(self, tracks=(), field=None):
        return FakeBF(self.me, self.zone, self.mem, tracks, field)

    def _select(self, field=None, tracks=(), now=5.0):
        bf = self._bf(tracks, field)
        return self.chooser.select(bf, bf.field, now)

    def test_first_secondary_is_taken(self) -> None:
        self.mem.items[8001] = item()
        pick = self._select()
        self.assertIsNotNone(pick)
        self.assertEqual(pick.id, 8001)

    def test_zone_deadline_veto(self) -> None:
        self.mem.items[8001] = item()
        self.assertIsNone(self._select(field=FakeField(deadline=6.0), now=5.0))

    def test_slot_full_does_not_swap(self) -> None:
        self.mem.items[8001] = item()
        self.me["weapons"] = [self.me["weapons"][0],
                              {"kind": "lightning", "cooldown": 0.0, "ammo": 0,
                               "reload": 0.0, "stats": {}}]
        self.assertIsNone(self._select())

    def test_laser_beats_mortar(self) -> None:
        self.mem.items[8001] = item(8001, detail="mortar")
        self.mem.items[8002] = item(8002, x=60.0, detail="laser")
        pick = self._select()
        self.assertEqual(pick.id, 8002)

    def test_receding_enemy_improves_race(self) -> None:
        # enemy 5 m from the item: heading away is a worse competitor than
        # heading at it, by the turn penalty
        away = track(5, 105.0, 0.0, vel=(12.0, 0.0, 0.0))
        toward = track(5, 105.0, 0.0, vel=(-12.0, 0.0, 0.0))
        p_away, _ = self.chooser._race(self._bf([away]), (100.0, 0.0), 11.0, 5.0)
        p_toward, _ = self.chooser._race(self._bf([toward]), (100.0, 0.0), 11.0, 5.0)
        self.assertGreater(p_away, p_toward)

    def test_approaching_enemy_on_item_vetoes(self) -> None:
        self.mem.items[8001] = item(x=100.0)
        near = track(5, 101.0, 0.0)
        self.assertIsNone(self._select(tracks=[near]))

    def test_far_receding_enemy_does_not_veto(self) -> None:
        self.mem.items[8001] = item(x=100.0)
        far = track(5, 180.0, 0.0, vel=(12.0, 0.0, 0.0))
        self.assertIsNotNone(self._select(tracks=[far]))

    def test_item_threat_veto(self) -> None:
        self.mem.items[8001] = item(x=100.0)
        # a laser carrier that can see the item, inside 120 m
        gunner = track(5, 60.0, 0.0, weapons=("laser",), aim=(0.0, 0.0))
        gunner.hp = 1400.0
        self.assertIsNone(self._select(tracks=[gunner]))

    def test_cube_value_drops_above_cap(self) -> None:
        below = self.chooser._cube_value(9, 1.0)
        above = self.chooser._cube_value(22, 1.0)
        self.assertGreater(below, above)

    def test_cube_near_threshold_bonus(self) -> None:
        just_below = self.chooser._cube_value(5, 1.0)
        middle = self.chooser._cube_value(8, 1.0)
        self.assertGreater(just_below, middle)

    def test_take_requires_reach(self) -> None:
        self.mem.items[8001] = item(x=100.0)
        pick = self._select()
        self.assertIsNone(self.chooser.take_id(self._bf(), pick))
        self.mem.items[8001].pos = (1.0, 0.0, 0.0)
        pick2 = self._select()
        self.assertEqual(self.chooser.take_id(self._bf(), pick2), (8001, None))

    def test_grab_adjacent_bypasses_the_trip_gate(self) -> None:
        # standing on a wanted weapon is free loot even when no trip is scored
        self.mem.items[8001] = item(x=1.0)
        self.assertIsNone(self._select(field=FakeField(deadline=6.0), now=5.0))
        self.assertEqual(self.chooser.grab_adjacent(self._bf(), 5.0), (8001, None))
        self.me["weapons"] = [self.me["weapons"][0], {"kind": "laser", "stats": {}}]
        self.assertIsNone(self.chooser.grab_adjacent(self._bf(), 5.0))

    def test_second_take_is_quarantined(self) -> None:
        self.mem.items[8001] = item(x=1.0)
        self.assertEqual(self.chooser.grab_adjacent(self._bf(), 5.0), (8001, None))
        self.assertIsNone(self.chooser.grab_adjacent(self._bf(), 5.1))
        self.assertEqual(self.chooser.grab_adjacent(self._bf(), 5.5), (8001, None))

    def test_mortar_in_slot1_is_swapped_for_a_laser(self) -> None:
        from mechbot import tuning
        old = tuning.LOOT_SWAP_ENABLE
        tuning.LOOT_SWAP_ENABLE = True
        try:
            self.me["weapons"] = [self.me["weapons"][0],
                                  {"kind": "mortar", "cooldown": 0.0, "ammo": 0,
                                   "reload": 0.0, "stats": {}}]
            self.mem.items[8001] = item(x=1.0, detail="laser")
            self.assertEqual(self.chooser.grab_adjacent(self._bf(), 5.0), (8001, 1))
        finally:
            tuning.LOOT_SWAP_ENABLE = old

    def test_mortar_is_not_swapped_for_a_worse_weapon(self) -> None:
        from mechbot import tuning
        old = tuning.LOOT_SWAP_ENABLE
        tuning.LOOT_SWAP_ENABLE = True
        try:
            self.me["weapons"] = [self.me["weapons"][0],
                                  {"kind": "mortar", "cooldown": 0.0, "ammo": 0,
                                   "reload": 0.0, "stats": {}}]
            self.mem.items[8001] = item(x=1.0, detail="mortar")
            self.assertIsNone(self.chooser.grab_adjacent(self._bf(), 5.0))
        finally:
            tuning.LOOT_SWAP_ENABLE = old


if __name__ == "__main__":
    unittest.main()
