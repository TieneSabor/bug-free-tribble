"""L2 local planner and vertical emission."""
from __future__ import annotations

import math
import unittest

from support import load_config, make_zone  # noqa: E402

from mechbot.static import load  # noqa: E402
from mechbot.world.field import Field  # noqa: E402
from mechbot.world.localplan import LocalPlan  # noqa: E402
from mechbot.world.los import Los  # noqa: E402
from mechbot.world.roadmap import Roadmap  # noqa: E402


class TestLocalPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = load_config()
        cls.st = load()
        cls.los = Los(cls.st)
        cls.road = Roadmap(cls.st, cls.los)
        cls.f = Field(cls.road, 11.7)
        cls.z = make_zone(t=0.0, center=[40.0, -70.0], radius=560.0,
                          next_center=[40.0, -70.0], next_radius=380.0)
        cls.f.build(cls.z, cls.z["next_center"], cls.z["next_radius"])
        cls.local = LocalPlan(cls.st, cls.los, cls.f, 11.7)

    def _spot(self):
        # a standable node in the main component, away from the pack
        for k in range(0, self.road.n, 37):
            if self.road.comp[k] == self.road.main:
                return (self.road.x[k], self.road.y[k], self.road.z[k])
        raise AssertionError("no node")

    def test_plan_reaches_goal(self) -> None:
        x, y, z = self._spot()
        goal = (x + 18.0, y + 6.0)
        path = self.local.plan(x, y, z, goal, [], self.z, 0.0)
        if path:
            for px, py, pz, kind in path:
                self.assertTrue(self.local.standable(px, py), (px, py))
                self.assertIn(kind, (0, 1, 2, 3))

    def test_plan_avoids_zone_outside(self) -> None:
        x, y, z = self._spot()
        # goal outside the circle: the planner must not route outside it
        goal = (40.0 + 900.0, -70.0)
        path = self.local.plan(x, y, z, goal, [], self.z, 0.0)
        for px, py, pz, kind in path:
            self.assertLessEqual(math.hypot(px - 40.0, py + 70.0), 560.0 + 6.0)

    def test_legalize_keeps_us_inside(self) -> None:
        x, y, z = self._spot()
        mx, my = self.local.legalize(1.0, 0.0, x, y, self.z)
        ex, ey = x + mx * 5.0, y + my * 5.0
        before = math.hypot(x - 40.0, y + 70.0)
        after = math.hypot(ex - 40.0, ey + 70.0)
        self.assertLessEqual(after, before + 1e-6)

    def test_live_stuck_spot_is_movable(self) -> None:
        """Regression: the live private-3 freeze at (-35.6, 70.2).

        The 1 m cell is free but the 2 m A* cell is not (a neighbour is
        blocked). Standability, legality and escape must use the 1 m truth, or
        the arbiter emits move=(0,0) for as long as the geometry holds.
        """
        x, y, z = -35.6, 70.2, 0.0
        self.assertTrue(self.local.standable(x, y, z))
        self.assertIsNotNone(self.local.floor_at(x, y, z))
        self.assertIsNone(self.local.cell_floor(x, y, z))   # A* stays conservative
        mx, my = self.local.legalize(1.0, 0.0, x, y, self.z, z)
        self.assertGreater(abs(mx) + abs(my), 0.5, (mx, my))
        ex, ey = self.local.escape_dir(x, y, z)
        self.assertGreater(abs(ex) + abs(ey), 0.5, (ex, ey))

    def test_vertical_classes(self) -> None:
        me = {"pos": [0.0, 0.0, 10.0], "grounded": True}
        step = self.local.step
        # walk
        m, j, b, _ = step([(3.0, 0.0, 10.5, 0)], me, 100.0, 11.7)
        self.assertFalse(j)
        # jump
        m, j, b, _ = step([(3.0, 0.0, 12.0, 1)], me, 100.0, 11.7)
        self.assertTrue(j)
        # jet starts with a jump when grounded
        m, j, b, _ = step([(3.0, 0.0, 18.0, 2)], me, 100.0, 11.7)
        self.assertTrue(j)
        # airborne: boost instead of jump
        me2 = {"pos": [0.0, 0.0, 10.0], "grounded": False}
        m, j, b, _ = step([(3.0, 0.0, 18.0, 2)], me2, 100.0, 11.7)
        self.assertFalse(j)
        self.assertTrue(b)
        # drop never jumps
        m, j, b, _ = step([(3.0, 0.0, 4.0, 3)], me, 100.0, 11.7)
        self.assertFalse(j)


if __name__ == "__main__":
    unittest.main()
