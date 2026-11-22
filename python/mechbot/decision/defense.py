"""A fire-only overlay: keep Zone movement, return fire without chasing."""
from __future__ import annotations

import math
from typing import Any, Optional

from mechbot import tuning
from mechbot.action.intent import Intent
from mechbot.config import Config
from mechbot.geometry import angle_diff, dist3
from mechbot.perception.battlefield import Battlefield


class Defense:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.last_aim = (0.0, 0.0)
        self.strafe_sign = 1.0
        self.strafe_until = 0.0

    def _pick(self, bf: Battlefield) -> Optional[Any]:
        me = bf.me.get("pos", (0.0, 0.0, 0.0))
        attacker = bf.attacker_since(tuning.DEFEND_ATTACKER_S)
        if attacker is not None and bf.targetable(attacker) and attacker.pos is not None:
            if dist3(me, attacker.pos) <= tuning.DEFEND_RADIUS_M:
                return attacker
        return bf.nearest_visible(tuning.DEFEND_RADIUS_M)

    def apply(self, bf: Battlefield, intent: Intent) -> Intent:
        if not tuning.ENABLE_DEFENSE:
            return intent
        target = self._pick(bf)
        if target is None or target.pos is None:
            return intent

        me = bf.me
        pos = me.get("pos", (0.0, 0.0, 0.0))
        weapons = me.get("weapons") or []
        w = weapons[0] if weapons else None
        if w is None:
            return intent
        stats = w.get("stats") or self.cfg.weapon("gun")
        speed = float(stats.get("speed", 252.0))
        wrng = float(stats.get("range", 230.0))
        cooldown = float(w.get("cooldown", 1.0))
        ammo = w.get("ammo")
        reloading = float(w.get("reload", 0.0) or 0.0)
        d3 = dist3(pos, target.pos)
        if d3 > 0.95 * wrng:
            return intent

        p = bf.lead_point(target, speed, tuning.ACTION_LATENCY_S)
        flight = 0.0
        for _ in range(2):
            if p is None:
                break
            p = bf.lead_point(target, speed, tuning.ACTION_LATENCY_S + flight)
            if p is None:
                break
            flight = dist3(bf.muzzle, p) / max(1.0, speed)
        if p is None:
            return intent

        move = intent.move
        if intent.label.startswith("zone:hold") or intent.label.startswith("encounter"):
            move = self._strafe(bf, intent.move, target)
        yaw = math.atan2(p[1] - pos[1], p[0] - pos[0])
        hd = math.hypot(p[0] - pos[0], p[1] - pos[1])
        pitch = math.atan2(p[2] - bf.muzzle[2], max(0.1, hd))
        self.last_aim = (yaw, pitch)

        cubes = target.cubes or 0
        hit_r = self.cfg.radius * (1.0 + self.cfg.size_per_cube * cubes) + self.cfg.gun_radius
        gate = min(
            math.radians(tuning.AIM_GATE_MAX_DEG),
            tuning.DEFEND_AIM_FRAC * math.atan2(hit_r, max(1.0, d3)),
        )
        actual = me.get("aim", (0.0, 0.0))
        err = max(abs(angle_diff(float(actual[0]), yaw)), abs(float(actual[1]) - pitch))
        clear = bf.shot_clear(target, p)
        can_fire = bool(
            ammo is not None
            and ammo > 0
            and cooldown <= 0.02
            and clear
            and err <= gate
        )
        reload_req = bool(
            ammo is not None and ammo <= 2 and not can_fire and reloading <= 0.0
        )
        return Intent(
            move=move,
            boost=intent.boost,
            jump=intent.jump,
            aim=(yaw, pitch),
            fire=(can_fire, False),
            reload=intent.reload or reload_req,
            take=intent.take,
            drop=intent.drop,
            pick=intent.pick,
            label=(intent.label + "|def") if intent.label else "def",
        )

    def _strafe(self, bf: Battlefield, move, target) -> tuple:
        if target.pos is None:
            return move
        if not bool(bf.me.get("in_zone", False)):
            return move
        if math.hypot(move[0], move[1]) < 0.05:
            return move
        if bf.t >= self.strafe_until:
            self.strafe_sign = -self.strafe_sign
            self.strafe_until = bf.t + tuning.STRAFE_FLIP_S
        me = bf.me.get("pos", (0.0, 0.0, 0.0))
        ux, uy = (target.pos[0] - me[0], target.pos[1] - me[1])
        n = math.hypot(ux, uy)
        if n < 1e-6:
            return move
        ux, uy = ux / n, uy / n
        tx, ty = -uy * self.strafe_sign, ux * self.strafe_sign
        mx = move[0] + tx * tuning.STRAFE_FRAC
        my = move[1] + ty * tuning.STRAFE_FRAC
        ln = math.hypot(mx, my)
        if ln > 1.0:
            mx, my = mx / ln, my / ln
        # Do not strafe through the zone edge.
        r = float(bf.zone.get("radius", 0.0))
        if r > 0.0:
            c = bf.zone.get("center", (0.0, 0.0))
            ex, ey = me[0] + mx * 4.0, me[1] + my * 4.0
            if math.hypot(ex - c[0], ey - c[1]) > max(0.0, r - tuning.STRAFE_EDGE_MARGIN_M):
                return move
        return mx, my
