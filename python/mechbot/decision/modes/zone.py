"""Zone rotation: HOLD, MOVE, RECOVERY."""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

from mechbot import tuning
from mechbot.action.intent import Intent
from mechbot.config import Config
from mechbot.decision.base import Mode
from mechbot.geometry import bearing, dist2, dot2, lerp2, normalize2
from mechbot.perception.battlefield import Battlefield
from mechbot.world.nav import NavGrid


class ZoneMode(Mode):
    name = "zone"
    min_dwell_s = tuning.ZONE_MIN_DWELL_S

    def __init__(self, cfg: Config, nav: NavGrid):
        self.cfg = cfg
        self.nav = nav
        self.recovery = False
        self.move_latched = False
        self.phase_key: Optional[Tuple[float, float, float]] = None
        self.path: List[Tuple[float, float]] = []
        self.path_goal: Optional[Tuple[float, float]] = None
        self.path_t = -1e9
        self.last_pos: Optional[Sequence[float]] = None
        self.last_t = 0.0
        self.stuck = 0.0

    # --- machine hooks ---------------------------------------------------
    def eligible(self, bf: Battlefield) -> bool:
        return True

    def priority(self, bf: Battlefield) -> int:
        if self.recovery:
            return tuning.ZONE_RECOVERY_PRIORITY
        if self.move_latched and not self._safe(bf):
            return tuning.ZONE_MOVE_PRIORITY
        return tuning.ZONE_HOLD_PRIORITY

    def enter(self, bf: Battlefield, prev: Optional[Mode]) -> None:
        self.path = []
        self.path_goal = None
        self.last_pos = None
        self.stuck = 0.0

    def exit(self, bf: Battlefield, nxt: Optional[Mode]) -> None:
        self.path = []
        self.path_goal = None

    def tick(self, bf: Battlefield) -> None:
        self._update_recovery(bf)
        self._update_phase(bf)

    # --- state -----------------------------------------------------------
    def _inside_live(self, bf: Battlefield) -> bool:
        z = bf.zone
        return dist2(bf.me.get("pos", (0.0, 0.0)), z.get("center", (0.0, 0.0))) <= float(
            z.get("radius", 0.0)
        )

    def _safe(self, bf: Battlefield) -> bool:
        z = bf.zone
        nr = float(z.get("next_radius", 0.0))
        if nr <= 0.5:
            return False
        clear = min(tuning.ZONE_SAFETY_M, 0.3 * nr)
        return dist2(bf.me.get("pos", (0.0, 0.0)), z.get("next_center", (0.0, 0.0))) <= nr - clear

    def _update_recovery(self, bf: Battlefield) -> None:
        in_zone = bool(bf.me.get("in_zone", self._inside_live(bf)))
        if not in_zone:
            self.recovery = True
        elif self.recovery and self._safe(bf):
            self.recovery = False

    def _update_phase(self, bf: Battlefield) -> None:
        z = bf.zone
        key = (
            round(float(z.get("shrink_start", 0.0)), 2),
            round(float(z.get("shrink_end", 0.0)), 2),
            round(float(z.get("next_radius", 0.0)), 2),
        )
        if key != self.phase_key:
            self.phase_key = key
            self.move_latched = False
        if self.recovery:
            self.move_latched = False
            return
        if self._safe(bf):
            self.move_latched = False
            return
        target = self._goal(bf, recovery=False)
        t_nom = self._t_nom(bf, target)
        trigger = float(z.get("shrink_start", 0.0)) - t_nom - tuning.ZONE_MOVE_MARGIN_S
        if bf.t >= trigger:
            self.move_latched = True

    # --- goals -----------------------------------------------------------
    def _clearance(self, radius: float) -> float:
        return min(tuning.ZONE_SAFETY_M, 0.3 * max(0.0, radius))

    def _goal(self, bf: Battlefield, recovery: bool) -> Tuple[float, float]:
        z = bf.zone
        me = bf.me.get("pos", (0.0, 0.0, 0.0))
        center = z.get("center", (0.0, 0.0))
        radius = float(z.get("radius", 0.0))
        next_c = z.get("next_center", (0.0, 0.0))
        next_r = float(z.get("next_radius", 0.0))
        dps = float(z.get("dps", 0.0))

        # At high damage while outside, cut to the live circle first.
        if recovery and dps >= 100.0 and not self._inside_live(bf):
            clear = self._clearance(radius)
            d = dist2(me, center)
            if d <= max(0.0, radius - clear):
                p = (float(center[0]), float(center[1]))
            else:
                ux, uy = normalize2(center[0] - me[0], center[1] - me[1])
                rr = max(0.0, radius - clear)
                p = (center[0] - ux * rr, center[1] - uy * rr)
            return self.nav.nearest_walkable(p[0], p[1])

        clear = self._clearance(next_r)
        rr = max(0.0, next_r - clear)
        d = dist2(me, next_c)
        if d <= rr:
            p = (float(next_c[0]), float(next_c[1]))
        else:
            ux, uy = normalize2(next_c[0] - me[0], next_c[1] - me[1])
            p = (next_c[0] - ux * rr, next_c[1] - uy * rr)
        p = lerp2(p, next_c, tuning.ZONE_HOLD_BIAS)
        return self.nav.nearest_walkable(p[0], p[1])

    def _walk_speed(self, bf: Battlefield) -> float:
        stats = bf.me.get("stats") or {}
        return max(1.0, float(stats.get("walk_speed", self.cfg.walk_speed)))

    def _t_nom(self, bf: Battlefield, target: Sequence[float]) -> float:
        d = dist2(bf.me.get("pos", (0.0, 0.0)), target)
        return d / self._walk_speed(bf) * tuning.ZONE_PATH_FACTOR + tuning.ZONE_ACCEL_ALLOWANCE_S

    # --- behavior --------------------------------------------------------
    def update(self, bf: Battlefield) -> Intent:
        if self.recovery:
            target = self._goal(bf, recovery=True)
            return self._move_to(bf, target, "zone:recovery", boost_allowed=True)
        if self.move_latched and not self._safe(bf):
            target = self._goal(bf, recovery=False)
            return self._move_to(bf, target, "zone:move", boost_allowed=True)
        # Even in HOLD, drift toward the next safe centre instead of standing
        # still until the deadline.  This is the starter's survival behaviour
        # with better pathing, and it avoids being an easy target.
        target = self._goal(bf, recovery=False)
        if dist2(bf.me.get("pos", (0.0, 0.0)), target) > 2.0:
            return self._move_to(bf, target, "zone:hold-move", boost_allowed=False)
        return self._hold(bf)

    def _hold(self, bf: Battlefield) -> Intent:
        me = bf.me.get("pos", (0.0, 0.0, 0.0))
        target = self._goal(bf, recovery=False)
        # Slow, silent orbit while waiting: 0.35 * walk speed stays below the
        # 5 m/s step-sound threshold and is harder to hit than standing still.
        rx, ry = normalize2(me[0] - target[0], me[1] - target[1])
        tx, ty = -ry, rx
        mx, my = tx * tuning.HOLD_ORBIT_FRAC, ty * tuning.HOLD_ORBIT_FRAC
        if not self.nav.local_clear(me[0], me[1], tx, ty, 2.0):
            mx, my = -mx, -my
            if not self.nav.local_clear(me[0], me[1], -tx, -ty, 2.0):
                mx, my = 0.0, 0.0
        search = bf.last_damage_bearing(tuning.SEARCH_S)
        if search is not None:
            yaw = search
        elif mx or my:
            yaw = math.atan2(my, mx)
        else:
            z = bf.zone
            base = bearing(me[0], me[1], z.get("center", (0.0, 0.0))[0], z.get("center", (0.0, 0.0))[1])
            yaw = base + 0.6 * math.sin(bf.t * 0.5)
        return Intent(move=(mx, my), aim=(yaw, 0.0), label="zone:hold")

    def _move_to(
        self, bf: Battlefield, target: Sequence[float], label: str, boost_allowed: bool
    ) -> Intent:
        me = bf.me.get("pos", (0.0, 0.0, 0.0))
        now = bf.t
        dist_target = dist2(me, target)
        blocked_here = not self.nav.is_walkable(me[0], me[1])
        if blocked_here or self.stuck > tuning.STUCK_S:
            ux, uy = normalize2(target[0] - me[0], target[1] - me[1])
            if abs(ux) + abs(uy) < 1e-6:
                wx, wy = self.nav.nearest_walkable(me[0], me[1])
                ux, uy = normalize2(wx - me[0], wy - me[1])
            if abs(ux) + abs(uy) < 1e-6:
                ux, uy = 1.0, 0.0
            energy = float(bf.me.get("energy", self.cfg.energy))
            self.stuck = 0.0
            return Intent(
                move=(ux, uy),
                boost=energy > 2.0,
                jump=True,
                aim=(math.atan2(uy, ux), 0.0),
                fire=(False, False),
                label="%s unstick" % label,
            )
        direct = False
        if dist_target > 1.0:
            ux, uy = normalize2(target[0] - me[0], target[1] - me[1])
            direct = self.nav.line_clear(me[0], me[1], ux, uy, dist_target, step=3.0)
        if direct:
            self.path = [(float(target[0]), float(target[1]))]
            self.path_goal = (float(target[0]), float(target[1]))
            self.path_t = now
        elif (
            not self.path
            or self.path_goal is None
            or now - self.path_t > tuning.PATH_RECOMPUTE_S
            or dist2(self.path_goal, target) > 5.0
        ):
            self.path = self.nav.path_cached(me, target)
            self.path_goal = (float(target[0]), float(target[1]))
            self.path_t = now

        while self.path and dist2(me, self.path[0]) < 3.0:
            self.path.pop(0)
        wp = self.path[0] if self.path else (target[0], target[1])
        dx, dy = wp[0] - me[0], wp[1] - me[1]
        d = math.hypot(dx, dy)
        if d < 1.5:
            dx = dy = 0.0
        else:
            dx, dy = dx / d, dy / d

        dx, dy = self._steer(bf, dx, dy)
        move_len = math.hypot(dx, dy)
        jump = False
        if self.last_pos is not None:
            dt = max(1e-3, now - self.last_t)
            moved = dist2(me, self.last_pos)
            if move_len > 0.1 and moved < 0.3:
                self.stuck += dt
            else:
                self.stuck = 0.0
            if self.stuck > tuning.STUCK_S:
                jump = True
                self.stuck = 0.0
        self.last_pos = (me[0], me[1], me[2])
        self.last_t = now

        boost = False
        if boost_allowed:
            energy = float(bf.me.get("energy", self.cfg.energy))
            z = bf.zone
            shrink_start = float(z.get("shrink_start", 0.0))
            remaining = max(0.0, shrink_start - now)
            dist_target = dist2(me, target)
            speed = self._walk_speed(bf)
            late = dist_target / max(1.0, speed) > remaining - 1.0
            outside = not bool(bf.me.get("in_zone", False))
            if jump:
                boost = False
            elif outside or (self.recovery and float(z.get("dps", 0.0)) >= 100.0):
                boost = energy > 5.0
            elif late and energy > tuning.BOOST_ENERGY_RESERVE:
                boost = True

        yaw = math.atan2(dy, dx) if move_len > 0.05 else bf.me.get("aim", (0.0, 0.0))[0]
        return Intent(
            move=(dx, dy),
            boost=boost,
            jump=jump,
            aim=(yaw, 0.0),
            fire=(False, False),
            label="%s d=%.0f" % (label, dist2(me, target)),
        )

    def _steer(self, bf: Battlefield, dx: float, dy: float) -> Tuple[float, float]:
        if dx == 0.0 and dy == 0.0:
            return 0.0, 0.0
        me = bf.me.get("pos", (0.0, 0.0, 0.0))
        if self.nav.local_clear(me[0], me[1], dx, dy, tuning.PROBE_M):
            return dx, dy
        base = math.atan2(dy, dx)
        best: Optional[Tuple[float, float]] = None
        best_score = -2.0
        for deg in (30, -30, 60, -60, 90, -90, 120, -120, 180):
            a = base + math.radians(deg)
            cx, cy = math.cos(a), math.sin(a)
            if self.nav.local_clear(me[0], me[1], cx, cy, tuning.PROBE_M):
                score = dot2(dx, dy, cx, cy)
                if score > best_score:
                    best_score = score
                    best = (cx, cy)
        return best if best is not None else (dx, dy)
