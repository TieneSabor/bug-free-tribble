"""Disengage entry/exit, TTK gate and heal bias."""
from __future__ import annotations

import math
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PYDIR = os.path.dirname(HERE)
if PYDIR not in sys.path:
    sys.path.insert(0, PYDIR)

from tests import support  # noqa: E402
from mechbot import tuning  # noqa: E402
from mechbot.decision.arbiter import Arbiter  # noqa: E402
from mechbot.decision.combat import Combat  # noqa: E402
from mechbot.perception.model import AgentTrack  # noqa: E402
from mechbot.perception.strength import StrengthField  # noqa: E402
from mechbot.perception.tracking import Perception  # noqa: E402
from mechbot.static import try_load  # noqa: E402
from mechbot.world.field import Field  # noqa: E402
from mechbot.world.localplan import LocalPlan  # noqa: E402
from mechbot.world.los import Los  # noqa: E402
from mechbot.world.roadmap import Roadmap  # noqa: E402
from tests.support import make_me, make_obs, make_zone, make_mech  # noqa: E402


def track(ident, x, y, hp=1400.0, weapons=("gun",), seen=0.0):
    t = AgentTrack(id=ident, kind="mech", pos=(x, y, 0.0), vel=(0.0, 0.0, 0.0),
                   aim=(0.0, 0.0), hp=hp, max_hp=1400.0, weapons=tuple(weapons))
    t.status = "visible"
    t.last_listed_t = seen
    t.last_visible_t = seen
    return t


class FakeBF:
    def __init__(self, me, zone, tracks=(), t=0.0, last_damage_t=-1e9):
        self.me = me
        self.zone = zone
        self.tracks = {x.id: x for x in tracks}
        self.t = t
        self.alive = 16
        self.last_damage_t = last_damage_t

    def last_damage_bearing(self, max_age_s=2.0):
        return None


class TestDisengage(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        st, err = try_load()
        if st is None:
            raise unittest.SkipTest("baked tables unavailable: %s" % err)
        cls.cfg = support.load_config()
        cls.los = Los(st)
        cls.road = Roadmap(st, cls.los)
        cls.field = Field(cls.road, 11.7)
        cls.local = LocalPlan(st, cls.los, cls.field, 11.7)
        cls.combat = Combat(cls.cfg, cls.los)

    def setUp(self) -> None:
        # the shipped default is off (see tuning); exercise the ledger logic
        self._flags = (tuning.HEAL_LEDGER_ENABLE, tuning.DISENGAGE_ENABLE)
        tuning.HEAL_LEDGER_ENABLE = True

    def tearDown(self) -> None:
        tuning.HEAL_LEDGER_ENABLE, tuning.DISENGAGE_ENABLE = self._flags

    def make(self):
        strength = StrengthField(self.cfg, self.road, 11.7)
        return Arbiter(self.cfg, self.road, self.field, self.local, self.combat,
                       self.los, random.Random(1), strength=strength)

    def threats(self, *rows):
        return [{"x": x, "y": y, "z": 0.0, "dps": dps, "dist": d,
                 "sees": sees, "id": i, "w": 1.0}
                for i, (x, y, dps, d, sees) in enumerate(rows)]

    def test_ttb_triggers(self) -> None:
        arb = self.make()
        bf = FakeBF(make_me(), make_zone())
        th = self.threats((50.0, 0.0, 150.0, 50.0, True),
                          (60.0, 10.0, 150.0, 61.0, True))
        self.assertTrue(arb._disengage_entry(bf, th, 0.6, 1.0, 10.0, 0.0, 100.0))

    def test_single_attacker_healthy_does_not_trigger(self) -> None:
        arb = self.make()
        bf = FakeBF(make_me(), make_zone())
        th = self.threats((80.0, 0.0, 80.0, 80.0, True))
        self.assertFalse(arb._disengage_entry(bf, th, 0.9, 30.0, 10.0, 10.0, 100.0))

    def test_two_attackers_below_seventy_percent(self) -> None:
        arb = self.make()
        me = make_me(hp=900.0)
        bf = FakeBF(me, make_zone(), tracks=[track(5, 80.0, 0.0), track(6, -70.0, 0.0)])
        for t in bf.tracks.values():
            t.last_damaged_us_t = 9.0
        th = self.threats((80.0, 0.0, 80.0, 80.0, True),
                          (-70.0, 0.0, 80.0, 70.0, True))
        self.assertTrue(arb._disengage_entry(bf, th, 0.64, 30.0, 10.0, 10.0, 100.0))

    def test_strength_ratio_triggers(self) -> None:
        arb = self.make()
        th = self.threats((70.0, 0.0, 200.0, 70.0, True))
        bf = FakeBF(make_me(), make_zone())
        self.assertTrue(arb._disengage_entry(bf, th, 0.8, 30.0, 10.0, 400.0, 100.0))

    def test_weakest_first(self) -> None:
        arb = self.make()
        me = make_me(hp=700.0)
        healthy = track(5, 80.0, 0.0, hp=1400.0)
        bf = FakeBF(me, make_zone(), tracks=[healthy])
        th = self.threats((80.0, 0.0, 80.0, 80.0, True))
        self.assertTrue(arb._disengage_entry(bf, th, 0.5, 30.0, 10.0, 10.0, 100.0))

    def test_no_attacker_no_entry(self) -> None:
        arb = self.make()
        bf = FakeBF(make_me(), make_zone())
        th = self.threats((200.0, 0.0, 80.0, 200.0, False))
        self.assertFalse(arb._disengage_entry(bf, th, 0.5, 30.0, 10.0, 999.0, 100.0))

    def test_ttk_gate(self) -> None:
        arb = self.make()
        me = make_me(hp=1400.0)
        bf = FakeBF(me, make_zone())
        easy = track(5, 100.0, 0.0, hp=400.0)
        hard = track(6, 100.0, 0.0, hp=1400.0, weapons=("laser",))
        self.assertTrue(arb._ttk_ok(bf, easy, 1400.0, 100.0))
        self.assertFalse(arb._ttk_ok(bf, hard, 300.0, 100.0))

    def test_isolation_needs_no_pack(self) -> None:
        arb = self.make()
        bf = FakeBF(make_me(), make_zone())
        lone = track(5, 100.0, 0.0)
        pack = [track(5, 100.0, 0.0), track(6, 130.0, 0.0), track(7, 90.0, 40.0)]
        bf_lone = FakeBF(make_me(), make_zone(), tracks=[lone])
        bf_pack = FakeBF(make_me(), make_zone(), tracks=pack)
        self.assertTrue(arb._isolated(bf_lone, lone, 100.0))
        self.assertFalse(arb._isolated(bf_pack, pack[0], 100.0))

    def test_heal_bias_tracks_the_field(self) -> None:
        arb = self.make()
        quiet = arb._heal_bias(0.75, 0.0, 100.0, 0.9, 10.0)
        normal = arb._heal_bias(0.75, 100.0, 100.0, 0.9, 10.0)
        loud = arb._heal_bias(0.75, 300.0, 100.0, 0.9, 10.0)
        self.assertLess(quiet, normal)
        self.assertLess(normal, loud)

    def test_heal_bias_deadline(self) -> None:
        arb = self.make()
        early = arb._heal_bias(0.45, 0.0, 100.0, 0.7, 10.0)
        late = arb._heal_bias(0.45, 0.0, 100.0, 0.7, 470.0)
        self.assertGreater(late, early)

    def test_no_hidden_goal_means_no_disengage(self) -> None:
        arb = self.make()
        bf = FakeBF(make_me(), make_zone())
        # no attackers visible: no goal, no mode
        self.assertIsNone(arb._disengage_goal(bf, [], 10.0, (0.0, 0.0, 0.0), 0.5, 0.85, 100.0))

    def test_under_pressure_is_safe_without_a_hidden_goal(self) -> None:
        # In open ground with no hidden node, the design says: do not retreat,
        # keep fighting or fall back to the filler. Assert we never invent a
        # goal and that the decision is still a legal action.
        arb = self.make()
        me = make_me(hp=700.0)
        mechs = [make_mech(5, x=60.0, y=0.0), make_mech(6, x=-50.0, y=20.0)]
        obs = make_obs(t=30.0, tick=600, me=me, mechs=mechs)
        obs["zone"] = make_zone(t=30.0, center=[0.0, 0.0], radius=560.0,
                                next_center=[0.0, 0.0], next_radius=380.0)
        perc = Perception(self.cfg, self.los)
        bf = perc.update(obs)
        intent = arb.decide(bf)
        self.assertIsNotNone(intent.label)
        if arb.dis_goal is None:
            self.assertNotIn("disengage", intent.label)
        else:
            self.assertIn("disengage", intent.label)
        self.assertLessEqual(math.hypot(*intent.move), 1.0 + 1e-9)
