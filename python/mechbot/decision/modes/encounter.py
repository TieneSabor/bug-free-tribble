"""Encounter: gun-only target acquisition, motion, and fire control."""
from __future__ import annotations

import math
import random
from typing import Any, List, Optional, Sequence, Tuple

from mechbot import tuning
from mechbot.action.intent import Intent
from mechbot.config import Config
from mechbot.decision.base import Mode
from mechbot.geometry import (
    angle_diff,
    bearing,
    clamp,
    dist2,
    dist3,
    dot2,
    normalize2,
    perp,
    wrap_angle,
)
from mechbot.perception.battlefield import Battlefield
from mechbot.world.nav import NavGrid


class EncounterMode(Mode):
    name = "encounter"
    min_dwell_s = tuning.ENCOUNTER_MIN_DWELL_S

    def __init__(self, cfg: Config, nav: NavGrid, rng: random.Random):
        self.cfg = cfg
        self.nav = nav
        self.rng = rng
        self.target_id: Optional[int] = None
        self.target_since = 0.0
        self.strafe_sign = 1.0
        self.strafe_until = 0.0
        self.path: List[Tuple[float, float]] = []
        self.path_goal: Optional[Tuple[float, float]] = None
        self.path_t = -1e9
        self.last_pos: Optional[Sequence[float]] = None
        self.last_t = 0.0
        self.stuck = 0.0
        self.last_target_t = -1e9
        self.last_aim = (0.0, 0.0)

    # --- machine hooks ---------------------------------------------------
    def _final_phase(self, bf: Battlefield) -> bool:
        z = bf.zone
        return (
            float(z.get("dps", 0.0)) >= 160.0
            and float(z.get("radius", 0.0)) <= tuning.ZONE_MIN_SAFE_RADIUS_M
        )

    def _engageable(self, bf: Battlefield, tr: Optional[Any], current: bool) -> bool:
        if not bf.targetable(tr) or tr is None or tr.pos is None:
            return False
        limit = tuning.DISENGAGE_RADIUS_M if current else tuning.ENGAGE_RADIUS_M
        return dist3(bf.me.get("pos", (0.0, 0.0, 0.0)), tr.pos) <= limit

    def eligible(self, bf: Battlefield) -> bool:
        if self._final_phase(bf):
            return False
        if self._engageable(bf, bf.track(self.target_id), current=True):
            return True
        if bf.nearest_visible(tuning.ENGAGE_RADIUS_M) is not None:
            return True
        return bf.t - self.last_target_t <= tuning.TARGET_LOST_S

    def priority(self, bf: Battlefield) -> int:
        return tuning.ENCOUNTER_PRIORITY

    def enter(self, bf: Battlefield, prev: Optional[Mode]) -> None:
        self.path = []
        self.path_goal = None
        self.last_pos = None
        self.stuck = 0.0
        self.target_since = bf.t
        self.last_target_t = bf.t
        self.last_aim = tuple(bf.me.get("aim", (0.0, 0.0)))
        if self.strafe_until <= bf.t:
            self.strafe_sign = 1.0
            self.strafe_until = bf.t + tuning.ORBIT_FLIP_S + self.rng.random() * 2.0

    def exit(self, bf: Battlefield, nxt: Optional[Mode]) -> None:
        self.target_id = None
        self.path = []
        self.path_goal = None
        self.last_target_t = -1e9

    def tick(self, bf: Battlefield) -> None:
        if bf.t >= self.strafe_until:
            self.strafe_sign = -self.strafe_sign
            self.strafe_until = bf.t + tuning.ORBIT_FLIP_S + self.rng.random() * 2.0

    # --- target choice ---------------------------------------------------
    def _choose_target(self, bf: Battlefield) -> Optional[Any]:
        cur = bf.track(self.target_id)
        if self._engageable(bf, cur, current=True):
            self.last_target_t = bf.t
            if bf.t - self.target_since >= tuning.TARGET_DWELL_S:
                me = bf.me.get("pos", (0.0, 0.0, 0.0))
                cur_d = dist3(me, cur.pos) if cur and cur.pos else 1e9
                attacker = bf.attacker_since(3.0)
                if (
                    attacker is not None
                    and attacker.id != cur.id
                    and self._engageable(bf, attacker, current=False)
                ):
                    self.target_id = attacker.id
                    self.target_since = bf.t
                    self.last_target_t = bf.t
                    return attacker
                near = bf.nearest_visible(tuning.ENGAGE_RADIUS_M)
                if near is not None and near.id != cur.id and near.pos is not None:
                    if dist3(me, near.pos) < 0.75 * cur_d:
                        self.target_id = near.id
                        self.target_since = bf.t
                        self.last_target_t = bf.t
                        return near
            return cur

        attacker = bf.attacker_since(3.0)
        if self._engageable(bf, attacker, current=False):
            self.target_id = attacker.id
            self.target_since = bf.t
            self.last_target_t = bf.t
            return attacker
        near = bf.nearest_visible(tuning.ENGAGE_RADIUS_M)
        if near is not None:
            self.target_id = near.id
            self.target_since = bf.t
            self.last_target_t = bf.t
            return near
        return None

    # --- update ----------------------------------------------------------
    def update(self, bf: Battlefield) -> Intent:
        target = self._choose_target(bf)
        if target is None:
            return Intent(aim=self.last_aim, label="enc:lost")
        me = bf.me
        pos = me.get("pos", (0.0, 0.0, 0.0))
        assert target.pos is not None
        d2 = dist2(pos, target.pos)
        d3 = dist3(pos, target.pos)

        weapons = me.get("weapons") or []
        w = weapons[0] if weapons else None
        stats = (w or {}).get("stats") or self.cfg.weapon("gun")
        speed = float(stats.get("speed", 252.0))
        wrng = float(stats.get("range", 230.0))
        cooldown = float((w or {}).get("cooldown", 1.0))
        ammo = (w or {}).get("ammo")
        reloading = float((w or {}).get("reload", 0.0) or 0.0)

        p = bf.lead_point(target, speed, tuning.ACTION_LATENCY_S)
        flight = 0.0
        for _ in range(2):
            if p is None:
                break
            p = bf.lead_point(target, speed, tuning.ACTION_LATENCY_S + flight)
            if p is None:
                break
            flight = dist3(bf.muzzle, p) / max(1.0, speed)

        yaw = me.get("aim", (0.0, 0.0))[0]
        pitch = me.get("aim", (0.0, 0.0))[1]
        clear = False
        if p is not None:
            yaw = math.atan2(p[1] - pos[1], p[0] - pos[0])
            hd = math.hypot(p[0] - pos[0], p[1] - pos[1])
            pitch = math.atan2(p[2] - bf.muzzle[2], max(0.1, hd))
            clear = bf.shot_clear(target, p)

        cubes = target.cubes or 0
        hit_r = self.cfg.radius * (1.0 + self.cfg.size_per_cube * cubes) + self.cfg.gun_radius
        gate = min(
            math.radians(tuning.AIM_GATE_MAX_DEG),
            tuning.AIM_GATE_FRAC * math.atan2(hit_r, max(1.0, d3)),
        )
        actual = me.get("aim", (0.0, 0.0))
        err = max(abs(angle_diff(float(actual[0]), yaw)), abs(float(actual[1]) - pitch))

        can_fire = bool(
            w is not None
            and ammo is not None
            and ammo > 0
            and cooldown <= 0.02
            and d3 <= 0.95 * wrng
            and clear
            and err <= gate
        )

        reload_req = bool(
            w is not None
            and ammo is not None
            and ammo <= 2
            and not can_fire
            and reloading <= 0.0
        )

        # --- motion ------------------------------------------------------
        retreat = self._retreating(bf, target)
        ux, uy = normalize2(target.pos[0] - pos[0], target.pos[1] - pos[1])
        tx, ty = perp(ux, uy)
        tx *= self.strafe_sign
        ty *= self.strafe_sign

        if d2 > tuning.BAND_HI_M + 20.0:
            desired = self._approach(bf, target, d2)
        else:
            if tuning.BAND_LO_M <= d2 <= tuning.BAND_HI_M:
                v_rad = 0.0
            else:
                r_star = clamp(d2, tuning.BAND_LO_M, tuning.BAND_HI_M)
                v_rad = clamp(tuning.RANGE_KP * (r_star - d2), -self._walk(bf), self._walk(bf))
            if target.vel is not None:
                v_rad -= dot2(target.vel[0], target.vel[1], ux, uy)
            if retreat:
                v_rad = -self._walk(bf)
            v_tan = tuning.ORBIT_FRAC * self._walk(bf)
            vx = ux * v_rad + tx * v_tan
            vy = uy * v_rad + ty * v_tan
            desired = normalize2(vx, vy)

        desired = self._dodge(bf, desired, tx, ty)
        desired = self._leash(bf, desired)
        dx, dy = self._probe(bf, desired)
        if not self.nav.is_walkable(pos[0], pos[1]) and target.pos is not None:
            dx, dy = normalize2(target.pos[0] - pos[0], target.pos[1] - pos[1])
        dlen = math.hypot(dx, dy)

        boost = False
        energy = float(me.get("energy", self.cfg.energy))
        if d2 > tuning.BOOST_GAP_M and dlen > 0.1 and energy > tuning.BOOST_ENERGY_RESERVE:
            boost = True
        if retreat and energy > 5.0:
            boost = True

        jump = self._stuck_jump(bf, dlen)
        aim_yaw = yaw if p is not None else float(actual[0])

        label = "enc t%d d=%.0f%s" % (
            target.id,
            d2,
            " fire" if can_fire else "",
        )
        return Intent(
            move=(dx, dy),
            boost=boost,
            jump=jump,
            aim=(aim_yaw, pitch),
            fire=(can_fire, False),
            reload=reload_req,
            label=label,
        )

    # --- motion helpers --------------------------------------------------
    def _walk(self, bf: Battlefield) -> float:
        stats = bf.me.get("stats") or {}
        return max(1.0, float(stats.get("walk_speed", self.cfg.walk_speed)))

    def _retreating(self, bf: Battlefield, target: Any) -> bool:
        hp = float(bf.me.get("hp", self.cfg.max_hp))
        mh = float(bf.me.get("max_hp", self.cfg.max_hp))
        if mh <= 0 or hp / mh >= 0.35:
            return False
        thp = target.hp_frac
        return thp is None or thp > hp / mh

    def _approach(
        self, bf: Battlefield, target: Any, d2: float
    ) -> Tuple[float, float]:
        assert target.pos is not None
        me = bf.me.get("pos", (0.0, 0.0, 0.0))
        ux, uy = normalize2(me[0] - target.pos[0], me[1] - target.pos[1])
        goal = (
            target.pos[0] + ux * max(tuning.BAND_LO_M, 70.0),
            target.pos[1] + uy * max(tuning.BAND_LO_M, 70.0),
        )
        goal = self.nav.nearest_walkable(goal[0], goal[1])
        now = bf.t
        dg = dist2(me, goal)
        ux2, uy2 = normalize2(goal[0] - me[0], goal[1] - me[1])
        if dg > 1.0 and self.nav.line_clear(me[0], me[1], ux2, uy2, dg, step=3.0):
            self.path = [(goal[0], goal[1])]
            self.path_goal = (goal[0], goal[1])
            self.path_t = now
        elif (
            not self.path
            or self.path_goal is None
            or now - self.path_t > tuning.PATH_RECOMPUTE_S
            or dist2(self.path_goal, goal) > 5.0
        ):
            self.path = self.nav.path_cached(me, goal)
            self.path_goal = (goal[0], goal[1])
            self.path_t = now
        while self.path and dist2(me, self.path[0]) < 3.0:
            self.path.pop(0)
        wp = self.path[0] if self.path else goal
        return normalize2(wp[0] - me[0], wp[1] - me[1])

    def _dodge(
        self, bf: Battlefield, desired: Tuple[float, float], tx: float, ty: float
    ) -> Tuple[float, float]:
        threats = bf.incoming(tuning.DODGE_HORIZON_S)
        for th in threats:
            if th["t"] <= tuning.DODGE_HORIZON_S and th["miss"] <= tuning.DODGE_RADIUS_M:
                self.strafe_sign = -self.strafe_sign
                return normalize2(tx, ty)
        return desired

    def _leash(self, bf: Battlefield, d: Tuple[float, float]) -> Tuple[float, float]:
        dx, dy = d
        if dx == 0.0 and dy == 0.0:
            return 0.0, 0.0
        me = bf.me.get("pos", (0.0, 0.0, 0.0))
        z = bf.zone
        c = z.get("center", (0.0, 0.0))
        r = float(z.get("radius", 0.0))
        margin = tuning.ZONE_EDGE_MARGIN_M
        ux, uy = normalize2(c[0] - me[0], c[1] - me[1])
        outward = dot2(dx, dy, ux, uy)
        if r <= 2.0 * margin:
            if outward < 0.0:
                dx -= ux * outward
                dy -= uy * outward
        else:
            ex, ey = me[0] + dx * tuning.PROBE_M, me[1] + dy * tuning.PROBE_M
            if dist2((ex, ey), c) > r - margin and outward < 0.0:
                dx -= ux * outward
                dy -= uy * outward
        return normalize2(dx, dy)

    def _probe(self, bf: Battlefield, d: Tuple[float, float]) -> Tuple[float, float]:
        if d[0] == 0.0 and d[1] == 0.0:
            return 0.0, 0.0
        me = bf.me.get("pos", (0.0, 0.0, 0.0))
        if self.nav.local_clear(me[0], me[1], d[0], d[1], tuning.PROBE_M):
            return d
        base = math.atan2(d[1], d[0])
        best: Optional[Tuple[float, float]] = None
        best_score = -2.0
        for deg in (30, -30, 60, -60, 90, -90, 120, -120, 180):
            a = base + math.radians(deg)
            cx, cy = math.cos(a), math.sin(a)
            if self.nav.local_clear(me[0], me[1], cx, cy, tuning.PROBE_M):
                score = dot2(d[0], d[1], cx, cy)
                if score > best_score:
                    best_score = score
                    best = (cx, cy)
        return best if best is not None else d

    def _stuck_jump(self, bf: Battlefield, dlen: float) -> bool:
        me = bf.me.get("pos", (0.0, 0.0, 0.0))
        jump = False
        if self.last_pos is not None:
            dt = max(1e-3, bf.t - self.last_t)
            moved = dist2(me, self.last_pos)
            if dlen > 0.1 and moved < 0.3:
                self.stuck += dt
            else:
                self.stuck = 0.0
            if self.stuck > tuning.STUCK_S:
                jump = True
                self.stuck = 0.0
        self.last_pos = (me[0], me[1], me[2])
        self.last_t = bf.t
        return jump
