"""Baked LOS vs the v1 polygon model."""
from __future__ import annotations

import random
import unittest

from support import load_config, load_hello  # noqa: E402

from mechbot.static import load  # noqa: E402
from mechbot.world.los import Los  # noqa: E402
from mechbot.world.mapmodel import MapModel  # noqa: E402


class TestLos(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = load_config()
        cls.st = load()
        cls.los = Los(cls.st)
        cls.mm = MapModel(load_hello()["map"], cls.cfg)
        cls.rng = random.Random(7)

    def _points(self):
        st = self.st
        x = st.min_x + self.rng.uniform(20, st.meta["nx"] - 20)
        y = st.min_y + self.rng.uniform(20, st.meta["ny"] - 20)
        g = float(st.occ["ground"][
            int(y - st.min_y) * st.nx + int(x - st.min_x)]) * 0.01
        return x, y, g

    def test_agrees_with_polygon_model(self) -> None:
        agree = 0
        total = 400
        for _ in range(total):
            x0, y0, g0 = self._points()
            x1, y1, g1 = self._points()
            a = (x0, y0, g0 + 7.0)
            b = (x1, y1, g1 + 4.5)
            mine = self.los.shot(a, b)
            theirs = not self.mm.los(a, b)
            agree += int(mine == theirs)
        self.assertGreaterEqual(agree / total, 0.97, agree / total)

    def test_clear_when_nothing_between(self) -> None:
        st = self.st
        # a short vertical segment above open ground must be clear
        x, y = 0.0, 0.0
        i = int(x - st.min_x)
        j = int(y - st.min_y)
        g = float(st.occ["ground"][j * st.nx + i]) * 0.01
        self.assertFalse(self.los.shot((x, y, g + 2.0), (x, y, g + 20.0)))

    def test_sight_is_stricter(self) -> None:
        shot = sight = 0
        for _ in range(300):
            x0, y0, g0 = self._points()
            x1, y1, g1 = self._points()
            a = (x0, y0, g0 + 8.0)
            b = (x1, y1, g1 + 4.5)
            shot += int(self.los.shot(a, b))
            sight += int(self.los.sight(a, b))
        self.assertGreaterEqual(sight, shot)


if __name__ == "__main__":
    unittest.main()
