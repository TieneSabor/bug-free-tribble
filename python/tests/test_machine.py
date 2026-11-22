"""Mode machine priority, dwell, and preemption tests."""
from __future__ import annotations

import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PYDIR = os.path.dirname(HERE)
if PYDIR not in sys.path:
    sys.path.insert(0, PYDIR)

from mechbot.action.intent import Intent  # noqa: E402
from mechbot.decision.base import Mode  # noqa: E402
from mechbot.decision.machine import ModeMachine  # noqa: E402


class FakeMode(Mode):
    def __init__(self, name: str, prio: int, eligible_at: float = 0.0, dwell: float = 0.0):
        self.name = name
        self._prio = prio
        self.eligible_at = eligible_at
        self.min_dwell_s = dwell

    def priority(self, bf) -> int:
        return self._prio

    def eligible(self, bf) -> bool:
        return bf.t >= self.eligible_at

    def update(self, bf) -> Intent:
        return Intent(label=self.name)


class TestMachine(unittest.TestCase):
    def test_priority_switch(self) -> None:
        a = FakeMode("a", 10)
        b = FakeMode("b", 30, eligible_at=5.0)
        m = ModeMachine([a, b])
        self.assertEqual(m.update(types.SimpleNamespace(t=0.0)).label, "a")
        self.assertEqual(m.update(types.SimpleNamespace(t=5.0)).label, "b")

    def test_dwell_blocks_small_gap(self) -> None:
        a = FakeMode("a", 10, dwell=2.0)
        b = FakeMode("b", 19, eligible_at=0.5)
        m = ModeMachine([a, b])
        self.assertEqual(m.update(types.SimpleNamespace(t=0.0)).label, "a")
        self.assertEqual(m.update(types.SimpleNamespace(t=1.0)).label, "a")
        self.assertEqual(m.update(types.SimpleNamespace(t=2.5)).label, "b")

    def test_survival_gap_preempts_dwell(self) -> None:
        a = FakeMode("a", 20, dwell=10.0)
        b = FakeMode("b", 40, eligible_at=0.5)
        m = ModeMachine([a, b])
        self.assertEqual(m.update(types.SimpleNamespace(t=0.0)).label, "a")
        self.assertEqual(m.update(types.SimpleNamespace(t=1.0)).label, "b")


if __name__ == "__main__":
    unittest.main()
