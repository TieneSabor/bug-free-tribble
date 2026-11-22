"""Map model and nav tests."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PYDIR = os.path.dirname(HERE)
if PYDIR not in sys.path:
    sys.path.insert(0, PYDIR)

from tests import support  # noqa: E402
from mechbot.world.mapmodel import MapModel, Prism  # noqa: E402
from mechbot.world.nav import NavGrid  # noqa: E402


class TestPrism(unittest.TestCase):
    def setUp(self) -> None:
        self.p = Prism(
            {
                "kind": "building",
                "base": 0.0,
                "top": 5.0,
                "ring": [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0],
                "holes": [[4.0, 4.0, 6.0, 4.0, 6.0, 6.0, 4.0, 6.0]],
            }
        )

    def test_contains_and_hole(self) -> None:
        self.assertTrue(self.p.contains_xy(2.0, 2.0))
        self.assertFalse(self.p.contains_xy(5.0, 5.0))
        self.assertFalse(self.p.contains_xy(12.0, 2.0))

    def test_segment_height(self) -> None:
        self.assertTrue(self.p.segment_hits((-1.0, 2.0, 2.0), (11.0, 2.0, 2.0)))
        self.assertFalse(self.p.segment_hits((-1.0, 2.0, 7.0), (11.0, 2.0, 7.0)))
        # Through the hole at y=5.
        self.assertFalse(self.p.segment_hits((4.5, 5.0, 2.0), (5.5, 5.0, 2.0)))


class TestRealMap(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        hello = support.load_hello()
        cls.cfg = support.Config(hello)
        cls.map = MapModel(hello["map"], cls.cfg)
        cls.nav = NavGrid(cls.map, cls.cfg)

    def test_height_and_bounds(self) -> None:
        h = self.map.height_at(-200.0, 100.0)
        self.assertTrue(-50.0 < h < 100.0)
        self.assertTrue(self.map.in_bounds(0.0, 0.0))
        self.assertFalse(self.map.in_bounds(-10000.0, 0.0))

    def test_some_walkable_path(self) -> None:
        cells = []
        for j in range(0, self.nav.ny, 7):
            for i in range(0, self.nav.nx, 7):
                if self.nav.is_walkable_cell((i, j)):
                    cells.append((i, j))
                    if len(cells) >= 12:
                        break
            if len(cells) >= 12:
                break
        self.assertGreaterEqual(len(cells), 2)
        a = self.nav.center_of(cells[0])
        b = self.nav.center_of(cells[-1])
        path = self.nav.path(a, b)
        self.assertTrue(path)
        self.assertTrue(self.nav.is_walkable(a[0], a[1]))


if __name__ == "__main__":
    unittest.main()
