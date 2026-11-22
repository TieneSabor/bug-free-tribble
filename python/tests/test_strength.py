"""Strength field: conservation, concentration and ray direction."""
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
from mechbot.perception.model import AgentTrack, Contact  # noqa: E402
from mechbot.perception.strength import StrengthField  # noqa: E402


class FakeRoad:
    def __init__(self, step=30.0, extent=420.0):
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


class FakeBF:
    def __init__(self, me, zone, tracks=(), contacts=(), items=None, alive=16):
        self.me = me
        self.zone = zone
        self.tracks = {t.id: t for t in tracks}
        self.contacts = list(contacts)
        self.items = items
        self.alive = alive

    def last_damage_bearing(self, max_age_s=2.0):
        return None


def zone(center=(0.0, 0.0), radius=560.0, next_center=(0.0, 0.0), next_radius=380.0):
    return support.make_zone(t=0.0, center=list(center), radius=radius,
                             next_center=list(next_center), next_radius=next_radius)


def track(ident=5, x=100.0, y=0.0, age=0.0, weapons=("gun",), hp=1400.0):
    t = AgentTrack(id=ident, kind="mech", pos=(x, y, 0.0), vel=(0.0, 0.0, 0.0),
                   hp=hp, max_hp=1400.0, weapons=tuple(weapons))
    t.last_listed_t = 0.0
    t.status = "visible"
    return t


class TestStrengthField(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = support.load_config()
        self.me = support.make_me()
        self.f = StrengthField(self.cfg, FakeRoad(), 11.7)

    def _bf(self, **kw):
        return FakeBF(self.me, zone(), **kw)

    def test_mass_is_conserved(self) -> None:
        for alive in (16, 9, 3):
            bf = self._bf(alive=alive)
            self.f.rebuild(bf, 10.0)
            self.assertAlmostEqual(self.f.total_count, alive - 1.0, places=4)

    def test_conserved_with_observations(self) -> None:
        bf = self._bf(alive=16, tracks=[track(5), track(6, x=-80.0)])
        self.f.rebuild(bf, 10.0)
        self.assertAlmostEqual(self.f.total_count, 15.0, places=4)
        self.assertGreater(self.f.total_power, 0.0)

    def test_empty_circle_has_no_mass(self) -> None:
        bf = self._bf(alive=1)
        self.f.rebuild(bf, 10.0)
        self.assertAlmostEqual(self.f.total_count, 0.0, places=6)

    def test_observed_track_concentrates_mass(self) -> None:
        bf = self._bf(tracks=[track(5, x=100.0, y=0.0)])
        self.f.rebuild(bf, 10.0)
        here = self.f.at(100.0, 0.0)
        far = self.f.at(-300.0, 250.0)
        self.assertGreater(here, 3.0 * max(far, 1e-6))

    def test_hurt_track_is_weaker(self) -> None:
        a = StrengthField(self.cfg, FakeRoad(), 11.7)
        a.rebuild(self._bf(tracks=[track(5, x=100.0, hp=1400.0)]), 10.0)
        b = StrengthField(self.cfg, FakeRoad(), 11.7)
        b.rebuild(self._bf(tracks=[track(5, x=100.0, hp=200.0)]), 10.0)
        self.assertGreater(a.at(100.0, 0.0), b.at(100.0, 0.0))

    def test_old_track_fades(self) -> None:
        a = StrengthField(self.cfg, FakeRoad(), 11.7)
        a.rebuild(self._bf(tracks=[track(5, x=100.0, age=0.0)]), 10.0)
        b = StrengthField(self.cfg, FakeRoad(), 11.7)
        b.rebuild(self._bf(tracks=[track(5, x=100.0, age=15.0)]), 25.0)
        self.assertGreater(a.at(100.0, 0.0), b.at(100.0, 0.0))

    def test_sound_ray_points_the_right_way(self) -> None:
        c = Contact(bearing=0.0, dist="mid", kind="gun", t=9.9)
        bf = self._bf(contacts=[c], alive=6)
        self.f.rebuild(bf, 10.0)
        east = self.f.at(110.0, 0.0)
        west = self.f.at(-110.0, 0.0)
        self.assertGreater(east, west)

    def test_path_risk_is_symmetric(self) -> None:
        bf = self._bf(tracks=[track(5, x=100.0, y=60.0)])
        self.f.rebuild(bf, 10.0)
        a = self.f.path_risk((0.0, 0.0), (200.0, 120.0))
        b = self.f.path_risk((200.0, 120.0), (0.0, 0.0))
        self.assertAlmostEqual(a, b, places=6)

    def test_rebuild_cadence(self) -> None:
        bf = self._bf()
        self.f.rebuild(bf, 10.0)
        self.assertFalse(self.f.due(10.1))
        self.assertTrue(self.f.due(10.5))
        self.assertTrue(self.f.due(10.1, force=True))


if __name__ == "__main__":
    unittest.main()
