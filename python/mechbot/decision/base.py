"""Mode protocol shared by the machine and the concrete modes."""
from __future__ import annotations

from typing import Optional

from mechbot.action.intent import Intent
from mechbot.perception.battlefield import Battlefield


class Mode:
    name = "mode"
    min_dwell_s = 0.0

    def priority(self, bf: Battlefield) -> int:
        return 0

    def eligible(self, bf: Battlefield) -> bool:
        raise NotImplementedError

    def enter(self, bf: Battlefield, prev: Optional["Mode"]) -> None:
        pass

    def exit(self, bf: Battlefield, nxt: Optional["Mode"]) -> None:
        pass

    def tick(self, bf: Battlefield) -> None:
        """Update cheap internal timers/latches even when this mode is not selected."""
        pass

    def update(self, bf: Battlefield) -> Intent:
        raise NotImplementedError
