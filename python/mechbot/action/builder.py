"""Turn an Intent into a protocol action dict."""
from __future__ import annotations

import math
from typing import Any, Dict, Optional, Sequence

import wire as mf

from mechbot.action.intent import Intent
from mechbot.config import Config
from mechbot.geometry import clamp, normalize2, wrap_angle


def _finite(v: float, default: float = 0.0) -> float:
    return v if math.isfinite(v) else default


class ActionBuilder:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.last_aim = (0.0, 0.0)

    def build(self, intent: Intent, obs: Dict[str, Any]) -> Dict[str, Any]:
        me = obs.get("self", {})
        weapons = me.get("weapons") or []
        mx, my = _finite(intent.move[0]), _finite(intent.move[1])
        n = math.hypot(mx, my)
        if n > 1.0:
            mx, my = mx / n, my / n
        elif n < 1e-9:
            mx = my = 0.0
        move = [mx, my]
        yaw = wrap_angle(_finite(intent.aim[0], self.last_aim[0]))
        pitch = clamp(_finite(intent.aim[1], self.last_aim[1]), self.cfg.min_pitch, self.cfg.max_pitch)
        self.last_aim = (yaw, pitch)

        fire = [bool(intent.fire[0]), bool(intent.fire[1])]
        if not weapons or weapons[0] is None:
            fire[0] = False
        if len(weapons) < 2 or weapons[1] is None:
            fire[1] = False

        action: Dict[str, Any] = {
            "tick": obs.get("tick", 0),
            "move": move,
            "aim": [yaw, pitch],
            "fire": fire,
        }
        if intent.boost:
            action["boost"] = True
        if intent.jump:
            action["jump"] = True
        if intent.reload:
            action["reload"] = True
        if intent.take is not None:
            action["take"] = intent.take
        if intent.drop is not None:
            action["drop"] = intent.drop

        pick: Optional[int] = intent.pick
        if pick is None and obs.get("offer") is not None:
            pick = 0
        if pick is not None:
            action["pick"] = int(pick)

        if intent.label:
            mf.draw.label(str(intent.label)[:80])
        return action

    def fallback(self, obs: Dict[str, Any]) -> Dict[str, Any]:
        yaw, pitch = self.last_aim
        return {
            "tick": obs.get("tick", 0),
            "move": [0.0, 0.0],
            "aim": [yaw, pitch],
            "fire": [False, False],
        }
