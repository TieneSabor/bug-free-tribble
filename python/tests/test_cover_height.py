"""Cover must be behind something *tall enough*, not merely behind something."""
from __future__ import annotations

import math
import os
import sys
import unittest
from array import array
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
PYDIR = os.path.dirname(HERE)
if PYDIR not in sys.path:
    sys.path.insert(0, PYDIR)

from mechbot.world.localplan import LocalPlan
from mechbot.world.los import Los

N = 40


def make_static(wall_top_m: float, wall_col: int = 20):
    """Flat 40x40 m grid, one full-height wall at x=wall_col."""
    cells = N * N
    ground = array("h", [0] * cells)
    base = array("h", [0] * cells)
    top = array("h", [0] * cells)
    cov = array("B", [0] * cells)
    free_g = array("B", [1] * cells)
    for j in range(N):
        k = j * N + wall_col
        cov[k] = 1
        top[k] = int(round(wall_top_m * 100))
        free_g[k] = 0
    occ = {
        "ground": ground, "base": base, "top": top, "cov": cov,
        "canopy": array("B", [0] * cells),
        "free_g": free_g, "free_r": array("B", [0] * cells),
    }
    n2 = N // 2
    layers = {
        "standable": array("B", [1] * (n2 * n2)),
        "floor": array("h", [0] * (n2 * n2)),
        "clear": array("B", [9] * (n2 * n2)),
        "wall": array("B", [9] * (n2 * n2)),
        "head": array("B", [255] * (n2 * n2)),
        "comp": array("H", [1] * (n2 * n2)),
    }
    st = SimpleNamespace(
        occ=occ, layers=layers,
        meta={"nx": N, "ny": N, "nx2": n2, "ny2": n2},
        min_x=0.0, min_y=0.0, nx=N, ny=N,
    )
    return st


class TestCoverHeight(unittest.TestCase):
    def _los(self, top_m):
        return Los(make_static(top_m))

    def test_low_wall_does_not_hide_the_body(self) -> None:
        los = self._los(2.0)
        eye = (30.0, 10.0, 8.0)          # enemy eye, 8 m up
        body = (16.0, 10.0, 4.5)         # our centre
        self.assertFalse(los.sight(eye, body), "a 2 m wall must not hide a 4.5 m body")

    def test_mid_wall_hides_body_but_not_top(self) -> None:
        los = self._los(6.0)
        eye = (30.0, 10.0, 8.0)
        self.assertTrue(los.sight(eye, (16.0, 10.0, 4.5)))
        self.assertFalse(los.sight(eye, (16.0, 10.0, 8.8)))

    def test_tall_wall_hides_everything(self) -> None:
        los = self._los(12.0)
        eye = (30.0, 10.0, 8.0)
        self.assertTrue(los.sight(eye, (16.0, 10.0, 4.5)))
        self.assertTrue(los.sight(eye, (16.0, 10.0, 8.8)))

    def test_find_cover_rejects_a_low_wall(self) -> None:
        st = make_static(2.0)
        los = Los(st)
        plan = LocalPlan(st, los, None, 11.7)
        # bot and threat are on the same side; every cell behind the wall is
        # still visible over 2 m, so there is no cover
        self.assertIsNone(plan.find_cover(25.0, 10.0, 0.0, (35.0, 10.0, 0.0), 12.0))

    def test_find_cover_accepts_a_tall_wall(self) -> None:
        st = make_static(12.0)
        los = Los(st)
        plan = LocalPlan(st, los, None, 11.7)
        spot = plan.find_cover(25.0, 10.0, 0.0, (35.0, 10.0, 0.0), 12.0)
        self.assertIsNotNone(spot)
        self.assertLess(spot[0], 20.0, "cover must be on the far side of the wall")
        # and it really is hidden from the threat's eye (sight() True = blocked)
        self.assertTrue(los.sight((35.0, 10.0, 8.0), (spot[0], spot[1], 4.5)))
        self.assertTrue(los.sight((35.0, 10.0, 8.0), (spot[0], spot[1], 8.8)))

    def test_terrain_ridge_hides(self) -> None:
        st = make_static(0.0)
        # raise the ground at x=20 to 12 m
        for j in range(N):
            st.occ["ground"][j * N + 20] = 1200
        los = Los(st)
        self.assertTrue(los.sight((30.0, 10.0, 8.0), (16.0, 10.0, 4.5)))


if __name__ == "__main__":
    unittest.main()
