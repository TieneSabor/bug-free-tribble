"""Select exactly one mode per tick and run it."""
from __future__ import annotations

from typing import List, Optional

import wire as mf

from mechbot import tuning
from mechbot.action.intent import Intent
from mechbot.decision.base import Mode
from mechbot.perception.battlefield import Battlefield


class ModeMachine:
    def __init__(self, modes: List[Mode]):
        self.modes = list(modes)
        self.current: Optional[Mode] = None
        self.entered_t = -1e9

    def _score(self, bf: Battlefield, mode: Mode) -> int:
        return mode.priority(bf) + (tuning.STICKY_BONUS if mode is self.current else 0)

    def update(self, bf: Battlefield) -> Intent:
        for m in self.modes:
            m.tick(bf)

        cands = [m for m in self.modes if m.eligible(bf)]
        if not cands:
            return Intent(label="idle")

        best = max(cands, key=lambda m: self._score(bf, m))
        cur = self.current

        if cur is not None and best is not cur:
            if cur in cands and (bf.t - self.entered_t) < cur.min_dwell_s:
                gap = best.priority(bf) - cur.priority(bf)
                if gap < tuning.PREEMPT_GAP:
                    best = cur

        if best is not cur:
            old = self.current
            if old is not None:
                old.exit(bf, best)
            best.enter(bf, old)
            self.current = best
            self.entered_t = bf.t
            mf.log(
                "[mode] t=%.1f %s->%s score=%d"
                % (bf.t, (old.name if old else "none"), best.name, self._score(bf, best))
            )

        return self.current.update(bf)
