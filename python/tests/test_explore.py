"""Explore filler: unvisited ground, main component, zone-feasible."""
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
from mechbot import tuning  # noqa: E402
from mechbot.decision.explore import ExplorePlanner  # noqa: E402


class FakeRoad:
    def __init__(self, step: float = 30.0, extent: float = 300.0, bad=None):
        pts = []
        k = int(extent / step)
        for i in range(-k, k + 1):
            for j in range(-k, k + 1):
                pts.append((i * step, j * step))
        self.x = [p[0] for p in pts]
        self.y = [p[1] for p in pts]
        self.n = len(pts)
        self.main = 0
        self.comp = [0] * self.n
        for idx, p in bad or ():
            if 0 <= idx < self.n:
                self.comp[idx] = 1

    def snap(self, x, y):
        best, bd = -1, 1e18
        for k in range(self.n):
            d = (self.x[k] - x) ** 2 + (self.y[k] - y) ** 2
            if d < bd:
                bd, best = d, k
        return best


class FakeField:
    def __init__(self, deadline=1e9, eta=(0.0,)):
        self._dl = deadline
        self.eta = list(eta)

    def deadline(self, zone, pos, now, margin=8.0):
        return self._dl


class FakeBF:
    def __init__(self, me, zone):
        self.me = me
        self.zone = zone


def make(road=None, field=None):
    cfg = support.load_config()
    return ExplorePlanner(cfg, road or FakeRoad(), field or FakeField())


def bf(x=0.0, y=0.0, radius=560.0, next_radius=380.0):
    me = support.make_me(x=x, y=y)
    zone = support.make_zone(t=0.0, center=[0.0, 0.0], radius=radius,
                             next_center=[0.0, 0.0], next_radius=next_radius,
                             shrink_start=60.0, shrink_end=110.0)
    return FakeBF(me, zone)


class TestExplore(unittest.TestCase):
    def setUp(self) -> None:
        # the shipped default is off (see tuning); test the planner logic
        self._old = tuning.EXPLORE_ENABLE
        tuning.EXPLORE_ENABLE = True

    def tearDown(self) -> None:
        tuning.EXPLORE_ENABLE = self._old

    def test_returns_a_goal_in_the_next_circle(self) -> None:
        pl = make()
        goal = pl.update(bf(), 1.0)
        self.assertIsNotNone(goal)
        self.assertLessEqual(math.hypot(*goal), 380.0)

    def test_goal_is_latched(self) -> None:
        pl = make()
        a = pl.update(bf(), 1.0)
        b = pl.update(bf(), 2.0)
        self.assertEqual(a, b)

    def test_visited_cells_are_skipped(self) -> None:
        pl = make()
        first = pl.update(bf(), 1.0)
        self.assertIsNotNone(first)
        # walk onto it: the cell is marked, a different goal comes back
        pl.visited.clear()
        second = pl.update(bf(first[0], first[1]), 10.0)
        self.assertNotEqual(second, first)

    def test_all_visited_returns_none(self) -> None:
        pl = make()
        for i in range(pl.nx):
            for j in range(pl.ny):
                pl.visited[(i, j)] = 0.0
        self.assertIsNone(pl.update(bf(), 1.0))

    def test_zone_deadline_rejects_everything(self) -> None:
        pl = make(field=FakeField(deadline=1.0))
        self.assertIsNone(pl.update(bf(), 5.0))

    def test_off_component_cells_are_skipped(self) -> None:
        # one node off the main component: a cell snapping to it must not be
        # chosen. Put the bad node on top of a cell centre far from us.
        road = FakeRoad()
        bad = []
        for k in range(road.n):
            if abs(road.x[k] - 90.0) < 1.0 and abs(road.y[k] - 90.0) < 1.0:
                bad.append((k, 1))
                break
        pl = make(road=FakeRoad(bad=bad))
        goal = pl.update(bf(), 1.0)
        self.assertIsNotNone(goal)
        self.assertFalse(abs(goal[0] - 90.0) < 30.0 and abs(goal[1] - 90.0) < 30.0)


if __name__ == "__main__":
    unittest.main()
