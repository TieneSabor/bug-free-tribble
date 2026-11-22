"""Arbiter: mode order, dodge, aim/fire."""
from __future__ import annotations

import random
import unittest

from support import (  # noqa: E402
    load_config,
    make_me,
    make_mech,
    make_obs,
    make_zone,
)

from mechbot.decision.arbiter import Arbiter, COVER, DODGE, HOLD, MUST, RECOVERY
from mechbot.decision.combat import Combat
from mechbot.perception.tracking import Perception
from mechbot.static import load
from mechbot.world.field import Field
from mechbot.world.localplan import LocalPlan
from mechbot.world.los import Los
from mechbot.world.roadmap import Roadmap


class TestArbiter(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = load_config()
        cls.st = load()
        cls.los = Los(cls.st)
        cls.road = Roadmap(cls.st, cls.los)
        cls.field = Field(cls.road, 11.7)
        cls.local = LocalPlan(cls.st, cls.los, cls.field, 11.7)
        cls.combat = Combat(cls.cfg, cls.los)

    def make(self):
        return Arbiter(self.cfg, self.road, self.field, self.local, self.combat,
                       self.los, random.Random(1))

    def run_obs(self, arb, obs):
        perc = Perception(self.cfg, self.los)
        bf = perc.update(obs)
        return arb.decide(bf), bf

    def test_recovery_when_outside(self) -> None:
        arb = self.make()
        obs = make_obs(t=1.0, tick=10, me=make_me(hp=1400.0))
        obs["self"]["in_zone"] = False
        obs["zone"] = make_zone(t=1.0, center=[0.0, 0.0], radius=560.0,
                                next_center=[0.0, 0.0], next_radius=380.0)
        intent, _ = self.run_obs(arb, obs)
        self.assertIn("recovery", intent.label)

    def test_hold_when_safe(self) -> None:
        arb = self.make()
        obs = make_obs(t=1.0, tick=10)
        obs["zone"] = make_zone(t=1.0, center=[0.0, 0.0], radius=560.0,
                                next_center=[0.0, 0.0], next_radius=380.0)
        intent, _ = self.run_obs(arb, obs)
        # the filler is HOLD, or EXPLORE when an unvisited cell is available
        self.assertTrue("hold" in intent.label or "explore" in intent.label,
                        intent.label)

    def test_must_when_slack_negative(self) -> None:
        arb = self.make()
        obs = make_obs(t=100.0, tick=1000)
        # 470 m from the next centre with 380 m radius: outside the next disc,
        # and the shrink has already started
        obs["self"]["pos"] = [460.0, 0.0, 0.0]
        obs["zone"] = make_zone(t=100.0, center=[0.0, 0.0], radius=470.0,
                                next_center=[0.0, 0.0], next_radius=380.0,
                                shrink_start=60.0, shrink_end=110.0, dps=20.0)
        intent, _ = self.run_obs(arb, obs)
        self.assertTrue(
            "must" in intent.label or "recovery" in intent.label, intent.label
        )

    def test_dodge_incoming_bullet(self) -> None:
        arb = self.make()
        me = make_me(hp=1400.0)
        obs = make_obs(t=2.0, tick=20, me=me)
        obs["projectiles"] = [{
            "id": 1, "kind": "gun",
            "pos": [30.0, 0.0, 4.0], "vel": [-250.0, 0.0, 0.0],
        }]
        intent, _ = self.run_obs(arb, obs)
        self.assertIn("dodge", intent.label)
        self.assertGreater(abs(intent.move[0]) + abs(intent.move[1]), 0.1)

    def test_fires_at_visible_target(self) -> None:
        # (-100, 300) is open ground with 60 m of clear sight to the east
        arb = self.make()
        me = make_me(x=-100.0, y=300.0, z=-4.3, hp=1400.0, yaw=0.0)
        mech = make_mech(ident=5, x=-40.0, y=300.0, z=-4.3)
        obs = make_obs(t=2.0, tick=20, me=me, mechs=[mech])
        intent, bf = self.run_obs(arb, obs)
        # aim at the target and pull the trigger when aligned and clear
        self.assertLess(abs(intent.aim[0]), 0.2, intent.aim)
        self.assertTrue(intent.fire[0] or intent.fire[1])


if __name__ == "__main__":
    unittest.main()
