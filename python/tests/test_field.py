"""Zone ETA field, deadline and slack."""
from __future__ import annotations

import math
import unittest

from support import make_zone  # noqa: E402

from mechbot.static import load  # noqa: E402
from mechbot.world.field import Field  # noqa: E402
from mechbot.world.los import Los  # noqa: E402
from mechbot.world.roadmap import Roadmap  # noqa: E402


class TestField(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.st = load()
        cls.road = Roadmap(cls.st, Los(cls.st))
        cls.f = Field(cls.road, 11.7)

    def _build(self):
        z = make_zone(t=0.0, center=[40.0, -70.0], radius=560.0,
                      next_center=[40.0, -70.0], next_radius=380.0,
                      shrink_start=60.0, shrink_end=110.0)
        self.f.build(z, z["next_center"], z["next_radius"])
        return z

    def test_eta_finite_and_monotone(self) -> None:
        z = self._build()
        n = self.road.n
        main = [k for k in range(n) if self.road.comp[k] == self.road.main]
        self.assertTrue(any(self.f.eta[k] < 1e8 for k in main))
        # following next[] reduces eta
        for k in main[:400]:
            v = self.f.next[k]
            if v >= 0 and self.f.eta[k] < 1e8:
                self.assertLessEqual(self.f.eta[v], self.f.eta[k] + 1e-6)

    def test_inside_has_time(self) -> None:
        z = self._build()
        p = (40.0, -70.0)
        dl = self.f.deadline(z, p, 0.0)
        self.assertGreater(dl, 60.0)

    def test_outside_has_no_time(self) -> None:
        z = self._build()
        p = (40.0 + 600.0, -70.0)
        self.assertLessEqual(self.f.deadline(z, p, 0.0), 60.0 + 1e-6)

    def test_deadline_during_shrink(self) -> None:
        z = make_zone(t=80.0, center=[0.0, 0.0], radius=470.0,
                      next_center=[0.0, 0.0], next_radius=380.0,
                      shrink_start=60.0, shrink_end=110.0)
        # 30 m inside the live edge: exits roughly 156 m of shrink later
        p = (470.0 - 8.0 - 30.0, 0.0)
        dl = self.f.deadline(z, p, 80.0)
        self.assertGreater(dl, 80.0)
        self.assertLessEqual(dl, 110.0 + 1e-6)

    def test_stale_on_phase_change(self) -> None:
        z = self._build()
        z2 = dict(z)
        z2["shrink_start"] = 110.0
        self.assertTrue(self.f.stale(z2, z["next_center"], z["next_radius"]))


if __name__ == "__main__":
    unittest.main()
