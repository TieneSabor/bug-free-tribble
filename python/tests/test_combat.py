"""Attack primitive: sticky target, aim solution, fire efficiency, readiness."""
from __future__ import annotations

import math
import os
import random
import sys
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
PYDIR = os.path.dirname(HERE)
if PYDIR not in sys.path:
    sys.path.insert(0, PYDIR)

from tests import support  # noqa: E402
from mechbot.decision.arbiter import Arbiter  # noqa: E402
from mechbot.decision.combat import Combat  # noqa: E402
from mechbot.perception.model import AgentTrack  # noqa: E402


class FakeLos:
    def __init__(self) -> None:
        self.blocked = False

    def shot(self, a, b) -> bool:
        return self.blocked

    def sight(self, a, b) -> bool:
        return self.blocked

    def fast(self, a, b) -> bool:
        return self.blocked


class FakeBF:
    def __init__(self, tracks=(), t: float = 0.0, aim=(0.0, 0.0), ammo=12):
        self.me = support.make_me(ammo=ammo)
        self.me["aim"] = list(aim)
        self.tracks = {tr.id: tr for tr in tracks}
        self.t = t
        self.zone = support.make_zone(t=t)
        self.cfg = support.load_config()
        self.projectiles = []

    def track(self, ident):
        return self.tracks.get(ident) if ident is not None else None

    def attacker_since(self, max_age_s=2.0):
        best = None
        bt = -1e9
        for tr in self.tracks.values():
            if tr.last_damaged_us_t is None:
                continue
            if self.t - tr.last_damaged_us_t <= max_age_s and tr.last_damaged_us_t > bt:
                best, bt = tr, tr.last_damaged_us_t
        return best

    def targetable(self, tr) -> bool:
        return bool(tr is not None and tr.status == "visible")

    def lead_point(self, track, speed, extra_t=0.1):
        if track.pos is None:
            return None
        z = track.pos[2] + 4.5
        if track.vel is None:
            return (track.pos[0], track.pos[1], z)
        return (
            track.pos[0] + track.vel[0] * extra_t,
            track.pos[1] + track.vel[1] * extra_t,
            z + track.vel[2] * extra_t,
        )

    @property
    def muzzle(self):
        return (self.me["pos"][0], self.me["pos"][1], self.me["pos"][2] + 7.0)


def mech(ident: int, x: float, y: float = 0.0) -> AgentTrack:
    tr = AgentTrack(id=ident, kind="mech", pos=(x, y, 0.0), vel=(0.0, 0.0, 0.0))
    tr.status = "visible"
    tr.hp = 1400.0
    tr.max_hp = 1400.0
    tr.weapons = ("gun",)
    tr.aim = (3.14, 0.0)
    return tr


def npc(ident: int, x: float, y: float = 0.0) -> AgentTrack:
    tr = AgentTrack(id=ident, kind="npc", pos=(x, y, 0.0), vel=(0.0, 0.0, 0.0))
    tr.status = "visible"
    tr.hp = 350.0
    tr.max_hp = 350.0
    return tr


def weapon(kind: str, **extra) -> dict:
    base = {
        "kind": kind,
        "cooldown": 0.0,
        "stats": {
            "damage": 315 if kind == "laser" else 60,
            "range": 280 if kind == "laser" else 45,
            "charge": 0.75,
            "min_charge": 0.15,
            "cooldown": 1.65 if kind == "laser" else 0.25,
            "cone_deg": 30.0,
            "energy": 3.0,
        },
    }
    if kind == "laser":
        base["charge"] = 0.0
    base.update(extra)
    return base


class TestCombatTarget(unittest.TestCase):
    def test_attacker_outranks_a_nearer_passive(self) -> None:
        far = mech(5, 100.0)
        far.last_damaged_us_t = 0.0
        near = mech(6, 50.0)
        bf = FakeBF([far, near], t=0.1)
        c = Combat(bf.cfg, FakeLos())
        picked = c.target(bf)
        self.assertIsNotNone(picked)
        self.assertEqual(picked.id, 5)

    def test_mech_outranks_close_npc(self) -> None:
        bf = FakeBF([mech(5, 100.0), npc(101, 20.0)])
        c = Combat(bf.cfg, FakeLos())
        picked = c.target(bf)
        self.assertIsNotNone(picked)
        self.assertEqual(picked.id, 5)

    def test_sticky_until_dwell_and_margin(self) -> None:
        first = mech(5, 100.0)
        bf = FakeBF([first], t=0.0)
        c = Combat(bf.cfg, FakeLos())
        self.assertEqual(c.target(bf).id, 5)

        closer = mech(6, 50.0)
        bf.tracks[6] = closer
        bf.t = 0.5
        self.assertEqual(c.target(bf).id, 5)     # dwell not elapsed
        bf.t = 1.1
        self.assertEqual(c.target(bf).id, 6)     # 25 % closer and dwell done

    def test_acquire_respects_weapon_range(self) -> None:
        bf = FakeBF([mech(5, 300.0)])
        c = Combat(bf.cfg, FakeLos())
        self.assertIsNone(c.target(bf))
        bf.tracks[5].pos = (210.0, 0.0, 0.0)
        self.assertIsNotNone(c.target(bf))

    def test_switches_to_a_dangerous_rival_even_if_farther(self) -> None:
        idle = mech(5, 60.0)
        bf = FakeBF([idle], t=0.0)
        c = Combat(bf.cfg, FakeLos())
        self.assertEqual(c.target(bf).id, 5)

        rival = mech(6, 100.0)
        rival.weapons = ("gun", "laser")
        bf.tracks[6] = rival
        bf.t = 1.1
        self.assertEqual(c.target(bf).id, 6)

    def test_mech_outranks_an_npc_attacker(self) -> None:
        drone = npc(101, 20.0)
        drone.last_damaged_us_t = 0.0
        bf = FakeBF([mech(5, 100.0), drone], t=0.1)
        c = Combat(bf.cfg, FakeLos())
        self.assertEqual(c.target(bf).id, 5)

    def test_npc_lock_yields_immediately_to_a_visible_mech(self) -> None:
        bf = FakeBF([npc(101, 20.0)], t=0.0)
        c = Combat(bf.cfg, FakeLos())
        self.assertEqual(c.target(bf).id, 101)
        bf.tracks[5] = mech(5, 100.0)
        bf.t = 0.1                                # before the normal dwell
        self.assertEqual(c.target(bf).id, 5)

    def test_dead_target_is_dropped(self) -> None:
        tr = mech(5, 60.0)
        bf = FakeBF([tr])
        c = Combat(bf.cfg, FakeLos())
        self.assertEqual(c.target(bf).id, 5)
        tr.dead = True
        self.assertIsNone(c.target(bf))
        self.assertIsNone(c.target_id)


class TestCombatFire(unittest.TestCase):
    def make(self, x=60.0, ammo=12, blocked=False, aim=(0.0, 0.0)):
        tr = mech(5, x)
        bf = FakeBF([tr], aim=aim, ammo=ammo)
        los = FakeLos()
        los.blocked = blocked
        c = Combat(bf.cfg, los)
        c.target(bf)
        return bf, los, c, tr

    def test_fires_at_aligned_clear_target(self) -> None:
        bf, _los, c, _tr = self.make()
        res = c.aim_fire(bf, bf.track(5))
        self.assertTrue(res["fire"][0])
        self.assertTrue(res["aligned"])
        self.assertTrue(res["clear"])
        self.assertFalse(res["reload"])

    def test_does_not_fire_through_cover(self) -> None:
        bf, _los, c, _tr = self.make(blocked=True)
        res = c.aim_fire(bf, bf.track(5))
        self.assertFalse(res["fire"][0])
        self.assertFalse(res["clear"])

    def test_does_not_fire_out_of_range(self) -> None:
        bf, _los, c, _tr = self.make(x=300.0)
        res = c.aim_fire(bf, bf.track(5))
        self.assertFalse(res["fire"][0])

    def test_does_not_fire_during_slew(self) -> None:
        bf, _los, c, _tr = self.make(aim=(0.5, 0.0))
        res = c.aim_fire(bf, bf.track(5))
        self.assertFalse(res["fire"][0])
        self.assertFalse(res["aligned"])

    def test_reload_only_when_a_shot_is_not_available(self) -> None:
        bf, los, c, _tr = self.make(ammo=1)
        res = c.aim_fire(bf, bf.track(5))
        self.assertTrue(res["fire"][0])
        self.assertFalse(res["reload"])

        los.blocked = True
        res = c.aim_fire(bf, bf.track(5))
        self.assertFalse(res["fire"][0])
        self.assertTrue(res["reload"])
        self.assertTrue(res["down"])

    def test_high_magazine_is_not_reloaded_in_cover(self) -> None:
        bf, los, c, _tr = self.make(ammo=8, blocked=True)
        res = c.aim_fire(bf, bf.track(5))
        self.assertFalse(res["reload"])

    def test_dry_gun_reports_reload_readiness(self) -> None:
        bf, _los, c, _tr = self.make(ammo=0)
        res = c.aim_fire(bf, bf.track(5))
        self.assertFalse(res["fire"][0])
        self.assertTrue(res["reload"])
        self.assertTrue(res["down"])
        self.assertGreaterEqual(res["next_ready_s"], 2.0)

    def test_idle_reload(self) -> None:
        bf, _los, c, _tr = self.make(ammo=5)
        self.assertTrue(c.idle_reload(bf))
        bf.me["weapons"][0]["ammo"] = 12
        self.assertFalse(c.idle_reload(bf))
        bf.me["weapons"][0]["ammo"] = 5
        bf.me["weapons"][0]["reload"] = 1.0
        self.assertFalse(c.idle_reload(bf))

    def test_missing_velocity_does_not_block_the_shot(self) -> None:
        bf, _los, c, tr = self.make()
        tr.vel = None
        res = c.aim_fire(bf, tr)
        self.assertTrue(res["fire"][0])
        self.assertLess(abs(res["aim"][0]), 0.1)

    def test_npc_aims_at_npc_height(self) -> None:
        tr = npc(101, 20.0)
        bf = FakeBF([tr])
        c = Combat(bf.cfg, FakeLos())
        c.target(bf)
        res = c.aim_fire(bf, tr)
        # Any point inside the 3.5 m drone body is a hit; aiming at the mech
        # COM (4.5 m) would pass over it.
        aim_z = 7.0 + math.tan(res["aim"][1]) * 20.0
        self.assertGreater(aim_z, 0.5)
        self.assertLess(aim_z, 3.5)


class TestCombatSecondSlot(unittest.TestCase):
    def test_laser_charges_then_releases(self) -> None:
        tr = mech(5, 100.0)
        bf = FakeBF([tr])
        bf.me["weapons"] = [None, weapon("laser")]
        c = Combat(bf.cfg, FakeLos())
        c.target(bf)
        res = c.aim_fire(bf, tr)
        self.assertTrue(res["fire"][1])          # charge
        bf.me["aim"] = list(res["aim"])
        bf.me["weapons"][1]["charge"] = 0.75
        res = c.aim_fire(bf, tr)
        self.assertFalse(res["fire"][1])         # release on target
        self.assertFalse(res["down"])

    def test_laser_cooldown_is_down_time(self) -> None:
        tr = mech(5, 100.0)
        bf = FakeBF([tr])
        bf.me["weapons"] = [None, weapon("laser", cooldown=1.2)]
        c = Combat(bf.cfg, FakeLos())
        c.target(bf)
        res = c.aim_fire(bf, tr)
        self.assertTrue(res["down"])
        self.assertAlmostEqual(res["next_ready_s"], 1.2, places=3)

    def test_lightning_requires_range_and_cone(self) -> None:
        tr = mech(5, 30.0)
        bf = FakeBF([tr], aim=(0.0, 0.0))
        bf.me["weapons"] = [None, weapon("lightning")]
        c = Combat(bf.cfg, FakeLos())
        c.target(bf)
        res = c.aim_fire(bf, tr)
        self.assertTrue(res["fire"][1])

        bf.me["aim"] = [0.6, 0.0]
        res = c.aim_fire(bf, tr)
        self.assertFalse(res["fire"][1])

        bf.me["aim"] = [0.0, 0.0]
        tr.pos = (60.0, 0.0, 0.0)
        res = c.aim_fire(bf, tr)
        self.assertFalse(res["fire"][1])


class TestAimModels(unittest.TestCase):
    def make(self, target, slot1=None, speed=None):
        bf = FakeBF([target])
        if slot1 is not None:
            bf.me["weapons"] = [None, slot1]
        if speed is not None:
            bf.me["weapons"][0]["stats"]["speed"] = speed
        c = Combat(bf.cfg, FakeLos())
        c.target(bf)
        return bf, c

    def test_our_own_velocity_does_not_change_the_solution(self) -> None:
        tr = mech(5, 100.0)
        tr.vel = (0.0, 8.0, 0.0)
        bf, c = self.make(tr)
        still = c.aim_fire(bf, tr)
        bf.me["vel"] = [11.7, 0.0, 0.0]
        moving = c.aim_fire(bf, tr)
        self.assertEqual(still["aim"], moving["aim"])
        self.assertEqual(still["fire"], moving["fire"])

    def test_gun_lead_and_com_pitch(self) -> None:
        tr = mech(5, 100.0)
        tr.vel = (0.0, 8.0, 0.0)          # crossing north at 8 m/s
        bf, c = self.make(tr)
        res = c.aim_fire(bf, tr)
        flight = 100.0 / 252.0
        expected = math.atan2(8.0 * (0.1 + flight), 100.0)
        self.assertAlmostEqual(res["aim"][0], expected, places=3)
        self.assertAlmostEqual(res["aim"][1], math.atan2(-2.5, 100.0), places=3)

    def test_gate_uses_one_tick_slew(self) -> None:
        tr = mech(5, 100.0)
        bf, c = self.make(tr)
        bf.me["aim"] = [-0.2, 0.0]       # one tick short of the command
        res = c.aim_fire(bf, tr)
        self.assertTrue(res["aligned"])
        self.assertTrue(res["fire"][0])

    def test_lead_beats_direct_aim_at_long_range(self) -> None:
        tr = mech(5, 120.0)
        tr.vel = (0.0, 8.0, 0.0)
        bf, c = self.make(tr)
        res = c.aim_fire(bf, tr)
        t_impact = 0.1 + 120.0 / 252.0
        aim_y = math.tan(res["aim"][0]) * 120.0
        target_y = 8.0 * t_impact
        self.assertLess(abs(aim_y - target_y), 0.5)   # our lead is correct
        self.assertGreater(abs(target_y), 3.0)        # direct aim misses

    def test_slower_gun_needs_more_lead(self) -> None:
        tr = mech(5, 100.0)
        tr.vel = (0.0, 8.0, 0.0)
        bf, c = self.make(tr, speed=120.0)
        fast_bf, fast_c = self.make(mech(5, 100.0))
        fast = fast_c.aim_fire(fast_bf, fast_bf.track(5))["aim"][0]
        slow = c.aim_fire(bf, tr)["aim"][0]
        self.assertGreater(slow, fast + 0.02)

    def test_laser_uses_release_latency_not_flight(self) -> None:
        tr = mech(5, 100.0)
        tr.vel = (0.0, 8.0, 0.0)
        bf, c = self.make(tr, slot1=weapon("laser"))
        res = c.aim_fire(bf, tr)
        self.assertAlmostEqual(
            res["aim"][0], math.atan2(8.0 * 0.1, 100.0), places=3
        )

    def test_lightning_pitch_is_irrelevant(self) -> None:
        tr = mech(5, 30.0)
        bf, c = self.make(tr, slot1=weapon("lightning"))
        bf.me["aim"] = [0.0, -0.7]        # pitch far below the drone COM
        res = c.aim_fire(bf, tr)
        self.assertTrue(res["fire"][1])
        self.assertFalse(res["aligned"])

    def test_mortar_uses_ballistic_solver(self) -> None:
        tr = mech(5, 100.0)
        mortar = {
            "kind": "mortar", "cooldown": 0.0,
            "stats": {
                "range": 230.0, "speed": 72.0, "gravity": 22.0,
                "cooldown": 2.6, "damage": 200.0, "splash_radius": 7.0,
            },
        }
        bf, c = self.make(tr, slot1=mortar)
        res = c.aim_fire(bf, tr)
        self.assertTrue(res["fire"][1])
        # Low arc over ~97 m from a 9.5 m tube, target body 1 m up.
        v, g, dx, dz = 72.0, 22.0, 97.0, 1.0 - 9.5
        disc = v ** 4 - g * (g * dx * dx + 2.0 * dz * v * v)
        expected = math.atan2(v * v - math.sqrt(disc), g * dx)
        self.assertAlmostEqual(res["aim"][1], expected, delta=0.08)


class StubLocal:
    def floor_at(self, x, y, z=None):
        return 0.0

    def exposure_at(self, x, y, z, threats, hard=False):
        return 0.0, 0.0

    def clearance(self, x, y):
        return 4


class CoverLos:
    def shot(self, a, b):
        return False

    def sight(self, a, b):
        # A wall to the west: only west candidates are hidden from the target.
        return b[0] < 0.0

    def fast(self, a, b):
        return self.sight(a, b)


class FightBF:
    def __init__(self):
        self.me = support.make_me()
        self.zone = {"center": [0.0, 0.0], "radius": 560.0}
        self.t = 1.0


class TestFightMovement(unittest.TestCase):
    def make_arb(self):
        arb = Arbiter.__new__(Arbiter)
        arb.cfg = support.load_config()
        arb.local = StubLocal()
        arb.los = CoverLos()
        arb._threat_list = []
        arb.rng = random.Random(1)
        arb.fight_strafe = 1.0
        arb.fight_strafe_until = 1e9
        arb.fight_cover_dir = (0.0, 0.0)
        arb.fight_cover_until = -1e9
        arb._dodge_vec = lambda bf: (0.0, 0.0)
        arb._lightning_close = lambda bf: False
        arb._dps = lambda t, d: 0.0
        return arb

    def test_ready_seeks_line_of_fire(self) -> None:
        arb = self.make_arb()
        bf = FightBF()
        target = mech(5, 100.0)
        move, _jump, _boost, sub = arb._fight_move(
            bf, 1.0, target, {"down": False}
        )
        self.assertGreater(move[0], 0.1)
        self.assertEqual(sub, "")

    def test_down_reload_prefers_cover(self) -> None:
        arb = self.make_arb()
        bf = FightBF()
        target = mech(5, 100.0)
        move, _jump, _boost, sub = arb._fight_move(
            bf, 1.0, target, {"down": True}
        )
        self.assertLess(move[0], -0.1)
        self.assertEqual(sub, "cov")

    def test_ready_rewards_target_rear_arc(self) -> None:
        arb = self.make_arb()
        arb.fight_strafe = 0.0
        bf = FightBF()
        target = mech(5, 85.0)
        target.aim = (math.pi / 2.0, 0.0)   # target faces north
        with patch("mechbot.tuning.ATTACK_REAR_BONUS", 100.0):
            move, _jump, _boost, _sub = arb._fight_move(
                bf, 1.0, target, {"down": False}
            )
        self.assertLess(move[1], -0.1)      # south is outside the front arc

    def test_laser_target_needs_real_cover(self) -> None:
        # The stub's only cover is a tree line west: `sight` is blocked but
        # `shot` is clear. A laser goes through that, so it must not count.
        arb = self.make_arb()
        bf = FightBF()
        target = mech(5, 100.0)
        target.weapons = ("gun", "laser")
        move, _jump, _boost, sub = arb._fight_move(
            bf, 1.0, target, {"down": True}
        )
        self.assertGreater(move[0], -0.05)
        self.assertEqual(sub, "")


if __name__ == "__main__":
    unittest.main()
