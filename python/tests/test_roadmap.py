"""Roadmap routing and cover."""
from __future__ import annotations

import random
import unittest

from support import load_config  # noqa: E402

from mechbot.static import load  # noqa: E402
from mechbot.world.los import Los  # noqa: E402
from mechbot.world.roadmap import Roadmap  # noqa: E402


class TestRoadmap(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.st = load()
        cls.los = Los(cls.st)
        cls.road = Roadmap(cls.st, cls.los)
        cls.rng = random.Random(3)

    def _main(self):
        nodes = [k for k in range(self.road.n) if self.road.comp[k] == self.road.main]
        return self.rng.choice(nodes)

    def test_snap(self) -> None:
        a = self._main()
        k = self.road.snap(self.road.x[a], self.road.y[a])
        self.assertGreaterEqual(k, 0)
        self.assertLess(abs(self.road.x[k] - self.road.x[a]), 30.0)

    def test_route_is_connected(self) -> None:
        for _ in range(5):
            a, b = self._main(), self._main()
            path = self.road.route(a, b)
            self.assertTrue(path, (a, b))
            self.assertEqual(path[0], a)
            self.assertEqual(path[-1], b)
            for u, v in zip(path, path[1:]):
                found = any(
                    self.road.dst[e] == v
                    for e in range(self.road.off[u], self.road.off[u + 1])
                )
                self.assertTrue(found, (u, v))

    def test_corridor(self) -> None:
        a, b = self._main(), self._main()
        c = self.road.corridor(
            self.road.x[a], self.road.y[a], self.road.x[b], self.road.y[b]
        )
        self.assertTrue(c.nodes)
        self.assertEqual(len(c.kinds), len(c.nodes) - 1)

    def test_cover_respects_sectors(self) -> None:
        a = self._main()
        threats = [(self.road.x[a] + 90.0, self.road.y[a], self.road.z[a])]
        got = self.road.cover(
            self.road.x[a], self.road.y[a], self.road.z[a], threats, 45.0
        )
        for k in got:
            body = (self.road.x[k], self.road.y[k], self.road.z[k] + 4.5)
            eye = (threats[0][0], threats[0][1], threats[0][2] + 8.0)
            self.assertTrue(self.los.sight(eye, body))


if __name__ == "__main__":
    unittest.main()
