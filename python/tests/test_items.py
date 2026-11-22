"""Item memory: what we remember, and when we drop it."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PYDIR = os.path.dirname(HERE)
if PYDIR not in sys.path:
    sys.path.insert(0, PYDIR)

from tests import support  # noqa: E402
from mechbot.perception.items import CRATE, CUBE, DROP, PICKUP, ItemMemory  # noqa: E402


def pickup(ident=8001, kind="laser", x=100.0, y=0.0, z=0.0):
    return {"id": ident, "kind": kind, "pos": [x, y, z]}


class TestItemMemory(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = support.load_config()
        self.mem = ItemMemory(self.cfg)

    def _obs(self, **kw):
        obs = support.make_obs(**kw)
        return obs

    def test_seen_pickup_is_remembered(self) -> None:
        obs = self._obs(t=1.0)
        obs["pickups"] = [pickup()]
        self.mem.update(obs, 1.0)
        it = self.mem.items[8001]
        self.assertEqual(it.kind, PICKUP)
        self.assertEqual(it.detail, "laser")

    def test_far_absence_keeps_memory(self) -> None:
        obs = self._obs(t=1.0)
        obs["pickups"] = [pickup()]
        self.mem.update(obs, 1.0)
        self.mem.update(self._obs(t=2.0), 2.0)
        self.assertIn(8001, self.mem.items)

    def test_near_absence_forgets(self) -> None:
        # we are standing on it and it is not listed any more: someone took it
        obs = self._obs(t=1.0, me=support.make_me(x=100.0, y=0.0))
        obs["pickups"] = [pickup()]
        self.mem.update(obs, 1.0)
        self.mem.update(self._obs(t=1.5, me=support.make_me(x=100.0, y=0.0)), 1.5)
        self.assertNotIn(8001, self.mem.items)

    def test_ttl_expiry(self) -> None:
        obs = self._obs(t=1.0)
        obs["pickups"] = [pickup()]
        self.mem.update(obs, 1.0)
        self.mem.update(self._obs(t=1.0 + 91.0), 1.0 + 91.0)
        self.assertNotIn(8001, self.mem.items)

    def test_take_failed_gone_forgets(self) -> None:
        obs = self._obs(t=1.0)
        obs["pickups"] = [pickup()]
        self.mem.update(obs, 1.0)
        obs2 = self._obs(t=2.0)
        obs2["events"] = [{"type": "take_failed", "id": 8001, "reason": "gone"}]
        self.mem.update(obs2, 2.0)
        self.assertNotIn(8001, self.mem.items)

    def test_took_forgets(self) -> None:
        obs = self._obs(t=1.0)
        obs["pickups"] = [pickup()]
        self.mem.update(obs, 1.0)
        obs2 = self._obs(t=2.0)
        obs2["events"] = [{"type": "took", "id": 8001, "kind": "laser", "slot": 1}]
        self.mem.update(obs2, 2.0)
        self.assertNotIn(8001, self.mem.items)

    def test_crate_and_cube(self) -> None:
        obs = self._obs(t=1.0)
        obs["crates"] = [{"id": 1007, "pos": [50.0, 0.0, 0.0], "hp": 300}]
        obs["cubes"] = [{"id": 5012, "pos": [60.0, 0.0, 0.0]}]
        self.mem.update(obs, 1.0)
        self.assertEqual(self.mem.items[1007].kind, CRATE)
        self.assertEqual(self.mem.items[1007].hp, 300.0)
        self.assertEqual(self.mem.items[5012].kind, CUBE)

    def test_drop_refresh_and_capture(self) -> None:
        obs = self._obs(t=1.0)
        obs["drops"] = [{"id": 20000, "pos": [10.0, 10.0, 0.0], "radius": 8,
                         "lands_in": 12.0, "capture_s": 4, "progress": 0,
                         "holder": None}]
        self.mem.update(obs, 1.0)
        it = self.mem.items[20000]
        self.assertEqual(it.kind, DROP)
        self.assertAlmostEqual(it.lands_in, 12.0)
        # drops are always known: absent from a later obs means it was captured
        self.mem.update(self._obs(t=2.0), 2.0)
        self.assertNotIn(20000, self.mem.items)


if __name__ == "__main__":
    unittest.main()
