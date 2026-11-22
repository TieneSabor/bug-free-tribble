"""Fire-while-moving overlay tests."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PYDIR = os.path.dirname(HERE)
if PYDIR not in sys.path:
    sys.path.insert(0, PYDIR)

from tests import support  # noqa: E402
from mechbot.action.intent import Intent  # noqa: E402
from mechbot.decision.defense import Defense  # noqa: E402
from mechbot.perception.model import AgentTrack  # noqa: E402


class FakeBF:
    def __init__(self, target):
        self.me = support.make_me(0.0, 0.0)
        self._target = target
        self.cfg = support.load_config()
        self.t = 0.0
        self.zone = support.make_zone(t=0.0, center=[0.0, 0.0], radius=560.0)

    def attacker_since(self, max_age_s=2.0):
        return None

    def targetable(self, tr) -> bool:
        return bool(tr is not None and tr.status == "visible")

    def nearest_visible(self, max_dist):
        if self._target is None:
            return None
        return self._target

    def lead_point(self, track, speed, extra_t=0.1):
        if track.pos is None:
            return None
        return (track.pos[0], track.pos[1], track.pos[2] + 4.5)

    def shot_clear(self, track, aim_point) -> bool:
        return True

    @property
    def muzzle(self):
        return (0.0, 0.0, 7.0)


class TestDefense(unittest.TestCase):
    def test_fires_while_keeping_move(self) -> None:
        target = AgentTrack(id=5, kind="mech", pos=(40.0, 0.0, 0.0), vel=(0.0, 0.0, 0.0))
        target.status = "visible"
        bf = FakeBF(target)
        d = Defense(bf.cfg)
        base = Intent(move=(0.35, 0.0), aim=(0.0, 0.0), label="zone:hold")
        first = d.apply(bf, base)
        self.assertNotEqual(first.move, base.move)
        self.assertGreater(abs(first.move[1]), 0.05)
        self.assertFalse(first.fire[0])
        bf.me["aim"] = list(first.aim)
        second = d.apply(bf, base)
        self.assertTrue(second.fire[0])
        self.assertNotEqual(second.move, base.move)

    def test_no_target_leaves_intent_unchanged(self) -> None:
        bf = FakeBF(None)
        d = Defense(bf.cfg)
        base = Intent(move=(0.5, 0.0), aim=(1.0, 0.0), label="zone:hold")
        out = d.apply(bf, base)
        self.assertEqual(out.move, base.move)
        self.assertEqual(out.aim, base.aim)
        self.assertEqual(out.label, base.label)

    def test_no_strafe_outside_zone(self) -> None:
        target = AgentTrack(id=5, kind="mech", pos=(40.0, 0.0, 0.0), vel=(0.0, 0.0, 0.0))
        target.status = "visible"
        bf = FakeBF(target)
        bf.me["in_zone"] = False
        d = Defense(bf.cfg)
        base = Intent(move=(1.0, 0.0), label="zone:hold-move")
        out = d.apply(bf, base)
        self.assertEqual(out.move, base.move)


if __name__ == "__main__":
    unittest.main()
