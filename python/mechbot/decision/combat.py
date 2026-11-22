"""Attack primitive: target pick, aim solution, fire efficiency, readiness.

Movement is owned by the arbiter. This module owns the target id, the aim
solution, and the per-slot trigger/reload decision, and exposes the weapon
readiness clock the fight loop uses to hide during reload/cooldown.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from mechbot import tuning
from mechbot.config import Config
from mechbot.geometry import angle_diff, clamp, dist3

Vec3 = Tuple[float, float, float]


class Combat:
    def __init__(self, cfg: Config, los):
        self.cfg = cfg
        self.los = los
        self.last_aim = (0.0, 0.0)
        self.target_id: Optional[int] = None
        self.target_since = -1e9
        self.last_target_t = -1e9
        self.last_solution: Optional[Dict[str, Any]] = None

    # --- target -------------------------------------------------------
    def _me_pos(self, bf) -> Vec3:
        return tuple(bf.me.get("pos", (0.0, 0.0, 0.0)))  # type: ignore[return-value]

    @staticmethod
    def _recent_attacker(bf, t) -> bool:
        return bool(
            t is not None
            and t.last_damaged_us_t is not None
            and bf.t - t.last_damaged_us_t < tuning.ATTACK_ATTACKER_S
        )

    def _stats(self, w: Dict[str, Any]) -> Dict[str, Any]:
        kind = str(w.get("kind") or "")
        return w.get("stats") or self.cfg.weapon(kind)

    def _best_range(self, bf) -> float:
        best = 0.0
        for w in (bf.me.get("weapons") or []):
            if not w:
                continue
            ws = self._stats(w)
            best = max(best, float(ws.get("range", 230.0)))
        return best or 230.0

    def _engageable(self, bf, t, current: bool) -> bool:
        if (
            t is None
            or t.kind not in ("mech", "npc")
            or t.dead
            or t.pos is None
            or t.status != "visible"
        ):
            return False
        d = dist3(self._me_pos(bf), t.pos)
        if t.kind == "npc":
            if d > tuning.ATTACK_NPC_RANGE_M:
                return False
            # A drone only earns a detour when it drew blood or is close.
            return self._recent_attacker(bf, t) or d <= tuning.ATTACK_NPC_IDLE_RANGE_M
        frac = tuning.ATTACK_KEEP_FRAC if current else tuning.ATTACK_ACQUIRE_FRAC
        return d <= self._best_range(bf) * frac

    def _score(self, bf, t) -> float:
        """Threat-weighted target score; lower is better.

        Distance is only half the score so a dangerous rival is not ignored in
        favour of a nearer passive house bot.
        """
        d = dist3(self._me_pos(bf), t.pos) if t.pos is not None else 1e9
        s = 0.5 * d
        if t.kind == "npc":
            s += 180.0
        if self._recent_attacker(bf, t):
            s -= 150.0
        hp = t.hp_frac
        if hp is not None:
            if hp < 0.25:
                s -= 50.0
            elif hp < 0.50:
                s -= 30.0
        kinds = set(t.weapons or ())
        if "laser" in kinds:
            s -= 60.0
        if "lightning" in kinds:
            s -= 30.0
        if "mortar" in kinds:
            s -= 15.0
        if t.aim is not None:
            me = self._me_pos(bf)
            brg = math.atan2(me[1] - t.pos[1], me[0] - t.pos[0])
            if abs(angle_diff(float(t.aim[0]), brg)) < 0.4:
                s -= 50.0
        return s

    def _best_visible(
        self, bf, exclude: Optional[int] = None, only_npc: bool = False
    ) -> Optional[Any]:
        cands: List[Any] = []
        for t in bf.tracks.values():
            if t.id == exclude:
                continue
            if not self._engageable(bf, t, current=False):
                continue
            if only_npc and t.kind != "npc":
                continue
            if not only_npc and t.kind != "mech":
                continue
            cands.append(t)
        if not cands:
            return None
        return min(cands, key=lambda t: self._score(bf, t))

    def _lock(self, bf, t) -> Any:
        if t.id != self.target_id:
            self.target_id = t.id
            self.target_since = bf.t
        self.last_target_t = bf.t
        return t

    def target(self, bf) -> Optional[Any]:
        """Pick one rival and keep it until a deliberate switch is worth it."""
        me = self._me_pos(bf)
        cur = bf.track(self.target_id)
        if self._engageable(bf, cur, current=True):
            assert cur is not None and cur.pos is not None
            # Never let a drone hold the lock while a mech is visible.
            if cur.kind == "npc":
                mech = self._best_visible(bf)
                if mech is not None:
                    return self._lock(bf, mech)
            dwell = bf.t - self.target_since >= tuning.TARGET_DWELL_S
            if dwell:
                attacker = bf.attacker_since(tuning.ATTACK_ATTACKER_S)
                if (
                    attacker is not None
                    and attacker.id != cur.id
                    and attacker.kind == "mech"
                    and not self._recent_attacker(bf, cur)
                    and self._engageable(bf, attacker, current=False)
                ):
                    return self._lock(bf, attacker)
                near = self._best_visible(bf, exclude=cur.id)
                if near is not None and near.pos is not None:
                    dc = dist3(me, cur.pos)
                    dn = dist3(me, near.pos)
                    if dn < tuning.ATTACK_SWITCH_FRAC * dc or (
                        self._score(bf, near) + tuning.ATTACK_SWITCH_SCORE
                        < self._score(bf, cur)
                    ):
                        return self._lock(bf, near)
            self.last_target_t = bf.t
            return cur

        if cur is not None:
            self.target_id = None

        attacker = bf.attacker_since(tuning.ATTACK_ATTACKER_S)
        if (
            attacker is not None
            and attacker.kind == "mech"
            and self._engageable(bf, attacker, current=False)
        ):
            return self._lock(bf, attacker)
        near = self._best_visible(bf)
        if near is not None:
            return self._lock(bf, near)
        if self._engageable(bf, attacker, current=False):
            return self._lock(bf, attacker)
        npc = self._best_visible(bf, only_npc=True)
        if npc is not None:
            return self._lock(bf, npc)
        return None

    # --- aim helpers ---------------------------------------------------
    def _point_at(self, bf, t, extra: float) -> Optional[Vec3]:
        if t.pos is None:
            return None
        cubes = t.cubes or 0
        scale = 1.0 + self.cfg.size_per_cube * cubes
        height = (
            float(self.cfg.npcs.get("height", 3.5))
            if t.kind == "npc" else self.cfg.height
        )
        z = t.pos[2] + 0.5 * height * scale
        if t.vel is None:
            return (t.pos[0], t.pos[1], z)
        return (
            t.pos[0] + t.vel[0] * extra,
            t.pos[1] + t.vel[1] * extra,
            z + t.vel[2] * extra,
        )

    def _slew_actual(self, bf, cmd: Tuple[float, float]) -> Tuple[float, float]:
        """Actual aim after one sim tick of slew toward `cmd`."""
        me = bf.me
        actual = me.get("aim", (0.0, 0.0))
        stats = me.get("stats") or {}
        yr = float(stats.get("turn_rate", self.cfg.turn_rate))
        pr = float(stats.get("pitch_rate", self.cfg.pitch_rate))
        dt = 0.05
        dy = clamp(angle_diff(float(cmd[0]), float(actual[0])), -yr * dt, yr * dt)
        dp = clamp(float(cmd[1]) - float(actual[1]), -pr * dt, pr * dt)
        return (
            float(actual[0]) + dy,
            clamp(float(actual[1]) + dp, self.cfg.min_pitch, self.cfg.max_pitch),
        )

    @staticmethod
    def _intercept_time(rel: Vec3, vel: Vec3, speed: float) -> Optional[float]:
        """Exact constant-velocity intercept: |rel + vel t| = speed t."""
        speed = max(1.0, speed)
        a = vel[0] * vel[0] + vel[1] * vel[1] + vel[2] * vel[2] - speed * speed
        b = 2.0 * (rel[0] * vel[0] + rel[1] * vel[1] + rel[2] * vel[2])
        c = rel[0] * rel[0] + rel[1] * rel[1] + rel[2] * rel[2]
        if abs(a) < 1e-9:
            if abs(b) < 1e-12:
                return None
            t = -c / b
            return t if t > 1e-6 else None
        disc = b * b - 4.0 * a * c
        if disc < 0.0:
            return None
        root = math.sqrt(disc)
        ts = [(-b - root) / (2.0 * a), (-b + root) / (2.0 * a)]
        ts = [t for t in ts if t > 1e-6]
        return min(ts) if ts else None

    def _lead(self, bf, t, speed: float, extra: float) -> Optional[Vec3]:
        p = self._point_at(bf, t, extra)
        if p is None:
            return None
        if t.vel is None:
            return p
        rel = (p[0] - bf.muzzle[0], p[1] - bf.muzzle[1], p[2] - bf.muzzle[2])
        flight = self._intercept_time(rel, t.vel, speed)
        if flight is None:
            return p
        q = self._point_at(bf, t, extra + flight)
        return q if q is not None else p

    def _aim_point(self, bf, p: Vec3, t) -> Tuple[Vec3, bool]:
        """Centre of mass first; fall back to chest/head if it is covered.

        The target is a tall cylinder, so COM leaves the most vertical margin
        against spread. NPC drones are only 3.5 m tall and need their own
        offsets.
        """
        span = 1.0 if t.kind == "npc" else 3.0
        for dz in (0.0, span * 2.0 / 3.0, -span * 2.0 / 3.0, span, -span):
            cand = (p[0], p[1], p[2] + dz)
            if not self.los.shot(bf.muzzle, cand):
                return cand, True
        return p, False


    @staticmethod
    def _mortar_pitches(dx: float, dz: float, v: float, g: float) -> List[float]:
        """Low and high launch pitches for a shell (metres, seconds)."""
        if dx < 1e-3:
            return [math.pi / 2.0] if dz >= 0.0 else []
        v2 = v * v
        disc = v2 * v2 - g * (g * dx * dx + 2.0 * dz * v2)
        if disc < 0.0:
            return []
        root = math.sqrt(disc)
        lo = math.atan2(v2 - root, g * dx)
        hi = math.atan2(v2 + root, g * dx)
        return [lo, hi] if hi - lo > 1e-6 else [lo]

    def _mortar_solution(self, bf, t, ws: Dict[str, Any]):
        """(yaw, pitch, flight, horizontal range, impact) or None.

        Constant velocity lead, low arc first, a self-splash guard and a coarse
        arc-clearance check. Trees do not stop shells; `los.shot` is the right
        predicate.
        """
        if t is None or t.pos is None:
            return None
        me = bf.me
        pos = self._me_pos(bf)
        v = float(ws.get("speed", 72.0))
        g = float(ws.get("gravity", 22.0))
        tube = float((me.get("stats") or {}).get("height", self.cfg.height)) + 0.5
        splash = float(ws.get("splash_radius", 7.0))
        safe = splash + self.cfg.radius + 2.5
        cubes = t.cubes or 0
        scale = 1.0 + self.cfg.size_per_cube * cubes
        height = (
            float(self.cfg.npcs.get("height", 3.5))
            if t.kind == "npc" else self.cfg.height * scale
        )
        aim_z = t.pos[2] + min(1.0, 0.3 * height)
        tvx, tvy = (t.vel[0], t.vel[1]) if t.vel is not None else (0.0, 0.0)
        delay = tuning.ACTION_LATENCY_S
        yaw = math.atan2(t.pos[1] - pos[1], t.pos[0] - pos[0])
        pitch = 0.2
        flight = 0.0
        px, py = t.pos[0], t.pos[1]
        for _ in range(4):
            px = t.pos[0] + tvx * (delay + flight)
            py = t.pos[1] + tvy * (delay + flight)
            yaw = math.atan2(py - pos[1], px - pos[0])
            ox = pos[0] + (self.cfg.radius + 0.5) * math.cos(yaw)
            oy = pos[1] + (self.cfg.radius + 0.5) * math.sin(yaw)
            dx = math.hypot(px - ox, py - oy)
            dz = aim_z - (pos[2] + tube)
            sols = self._mortar_pitches(dx, dz, v, g)
            chosen = None
            for candidate in sols:
                if self.cfg.min_pitch <= candidate <= self.cfg.max_pitch:
                    chosen = candidate
                    break
            if chosen is None:
                return None
            pitch = chosen
            flight = dx / max(1e-6, v * math.cos(pitch))
        impact = (px, py, aim_z)
        # Do not drop a shell on our own future position.
        fx = pos[0] + float(me.get("vel", (0.0, 0.0, 0.0))[0]) * min(flight, 1.5)
        fy = pos[1] + float(me.get("vel", (0.0, 0.0, 0.0))[1]) * min(flight, 1.5)
        if (math.hypot(impact[0] - fx, impact[1] - fy) < safe
                or math.hypot(impact[0] - pos[0], impact[1] - pos[1]) < safe):
            return None
        # Coarse arc clearance: a wall between the tube and the shell path
        # means the shell detonates next to us.
        ox = pos[0] + (self.cfg.radius + 0.5) * math.cos(yaw)
        oy = pos[1] + (self.cfg.radius + 0.5) * math.sin(yaw)
        oz = pos[2] + tube
        prev = (ox, oy, oz)
        for k in range(1, 6):
            tt = flight * (k / 5.0 if k < 5 else 0.97)
            pt = (
                ox + v * math.cos(pitch) * math.cos(yaw) * tt,
                oy + v * math.cos(pitch) * math.sin(yaw) * tt,
                oz + v * math.sin(pitch) * tt - 0.5 * g * tt * tt,
            )
            if self.los.shot(prev, pt):
                return None
            prev = pt
        return yaw, pitch, flight, math.hypot(px - ox, py - oy), impact

    def _hit_radius(self, t) -> float:
        if t.kind == "npc":
            return float(self.cfg.npcs.get("radius", 1.8)) + 0.6
        cubes = t.cubes or 0
        return (
            self.cfg.radius * (1.0 + self.cfg.size_per_cube * cubes)
            + self.cfg.gun_radius
        )

    @staticmethod
    def _hit_prob(d: float, hit_r: float, spread_deg: float, err: float) -> float:
        sigma = max(0.0, d * math.tan(math.radians(max(0.0, spread_deg))))
        offset = d * math.tan(max(0.0, err))
        if sigma <= 1e-4:
            return 1.0 if offset <= hit_r else 0.0
        tol = max(0.0, hit_r - offset)
        return clamp(1.0 - math.exp(-0.5 * (tol / sigma) ** 2), 0.0, 1.0)

    # --- aim + fire ---------------------------------------------------
    def aim_fire(self, bf, t) -> Dict[str, Any]:
        me = bf.me
        pos = self._me_pos(bf)
        muzzle = bf.muzzle
        weapons: Sequence[Optional[Dict[str, Any]]] = me.get("weapons") or []
        energy = float(me.get("energy", self.cfg.energy))
        d3 = dist3(pos, t.pos) if t is not None and t.pos is not None else 1e9

        aim = self.last_aim
        clear = False
        aligned = False
        hit_prob = 0.0
        prim_kind = ""
        prim_ws: Dict[str, Any] = {}
        prim_d = d3
        aim_point: Optional[Vec3] = None
        mortar_sol = None

        if t is not None and t.pos is not None:
            prim_slot = -1
            for i, w in enumerate(weapons[:2]):
                if w and w.get("kind") == "gun":
                    prim_slot = i
                    break
            if prim_slot < 0:
                for i, w in enumerate(weapons[:2]):
                    if w:
                        prim_slot = i
                        break
            if prim_slot >= 0:
                w = weapons[prim_slot]
                assert w is not None
                prim_kind = str(w.get("kind") or "")
                prim_ws = self._stats(w)
                if prim_kind == "gun":
                    p = self._lead(
                        bf, t, float(prim_ws.get("speed", 252.0)),
                        tuning.ACTION_LATENCY_S,
                    )
                elif prim_kind == "laser":
                    p = self._point_at(bf, t, tuning.ACTION_LATENCY_S)
                elif prim_kind == "mortar":
                    mortar_sol = self._mortar_solution(bf, t, prim_ws)
                    p = None
                    if mortar_sol is not None:
                        yaw, pitch, flight, dx, impact = mortar_sol
                        aim = (yaw, pitch)
                        prim_d = max(1.0, dx)
                        aim_point = impact
                        clear = True
                        fire_aim = self._slew_actual(bf, aim)
                        err_yaw = abs(angle_diff(fire_aim[0], yaw))
                        err_pitch = abs(fire_aim[1] - pitch)
                        v = float(prim_ws.get("speed", 72.0))
                        g = float(prim_ws.get("gravity", 22.0))
                        lat_miss = err_yaw * dx
                        rng_miss = err_pitch * (
                            v * v / g * abs(math.cos(2.0 * pitch)) * 2.0
                            + 10.0
                        )
                        aligned = math.hypot(lat_miss, rng_miss) < 5.0
                        hit_prob = 1.0 if aligned else 0.0
                else:
                    p = self._point_at(bf, t, tuning.ACTION_LATENCY_S)
                if p is not None:
                    actual = me.get("aim", (0.0, 0.0))
                    aim_point, clear = self._aim_point(bf, p, t)
                    yaw = math.atan2(aim_point[1] - pos[1], aim_point[0] - pos[0])
                    hd = math.hypot(aim_point[0] - pos[0], aim_point[1] - pos[1])
                    pitch = math.atan2(aim_point[2] - muzzle[2], max(0.1, hd))
                    aim = (yaw, pitch)
                    prim_d = dist3(muzzle, aim_point)
                    fire_aim = self._slew_actual(bf, aim)
                    err = max(
                        abs(angle_diff(fire_aim[0], yaw)),
                        abs(fire_aim[1] - pitch),
                    )
                    gate = min(
                        math.radians(tuning.AIM_GATE_MAX_DEG),
                        tuning.ATTACK_AIM_GATE_FRAC
                        * math.atan2(self._hit_radius(t), max(1.0, prim_d)),
                    )
                    aligned = err <= gate
                    spread = float(
                        prim_ws.get(
                            "spread_deg", 0.6 if prim_kind == "gun" else 0.0
                        )
                    )
                    hit_prob = self._hit_prob(
                        prim_d, self._hit_radius(t), spread, err
                    )

        self.last_aim = aim

        fire: List[bool] = [False, False]
        reload_req = False
        slot_ready: List[float] = [1e9, 1e9]
        for i, w in enumerate(weapons[:2]):
            if not w:
                continue
            kind = str(w.get("kind") or "")
            ws = self._stats(w)
            rng = float(ws.get("range", 230.0))
            cd = float(w.get("cooldown", 0.0) or 0.0)

            if kind == "gun":
                ammo = w.get("ammo")
                reloading = float(w.get("reload", 0.0) or 0.0)
                if reloading > 0.0:
                    nxt = reloading
                elif ammo is None or ammo <= 0:
                    nxt = float(ws.get("reload", 2.4))
                else:
                    nxt = max(0.0, cd)
                slot_ready[i] = nxt
                if (
                    ammo is not None
                    and ammo > 0
                    and reloading <= 0.0
                    and cd <= 0.02
                    and prim_d <= 0.95 * rng
                    and clear
                    and aligned
                    and hit_prob >= tuning.ATTACK_MIN_HIT_PROB
                ):
                    fire[i] = True

            elif kind == "laser":
                charge = float(w.get("charge", 0.0) or 0.0)
                full = float(ws.get("charge", 0.75))
                min_charge = float(ws.get("min_charge", 0.15))
                if cd > 0.0:
                    nxt = cd
                elif charge > 0.0 and charge >= min_charge:
                    nxt = 0.0
                elif charge > 0.0:
                    nxt = max(0.0, min_charge - charge)
                else:
                    nxt = 0.0
                slot_ready[i] = nxt
                if prim_d <= 0.97 * rng and clear and aligned:
                    if charge < full * 0.95:
                        fire[i] = True          # build the charge
                    elif charge >= min_charge:
                        fire[i] = False         # release on target
                    else:
                        fire[i] = True
                elif charge > 0.0:
                    fire[i] = True              # keep the beam ready
                else:
                    fire[i] = False

            elif kind == "lightning":
                cost = float(ws.get("energy", 3.0))
                slot_ready[i] = max(0.0, cd)
                # The arc is yaw-only and uses the actual torso direction.
                actual = me.get("aim", (0.0, 0.0))
                fire_aim = self._slew_actual(bf, aim)
                brg = 0.0
                if t is not None and t.pos is not None:
                    brg = math.atan2(
                        t.pos[1] - pos[1], t.pos[0] - pos[0]
                    )
                cone = math.radians(float(ws.get("cone_deg", 30.0))) * 0.5
                if (
                    t is not None
                    and t.pos is not None
                    and d3 <= rng - 1.0
                    and clear
                    and energy >= cost
                    and cd <= 0.02
                    and abs(angle_diff(fire_aim[0], brg)) <= cone - 0.05
                ):
                    fire[i] = True

            elif kind == "mortar":
                slot_ready[i] = max(0.0, cd)
                if mortar_sol is not None and cd <= 0.02 and aligned:
                    fire[i] = True


        # Safe reload: only when the gun cannot produce a shot now.
        for i, w in enumerate(weapons[:2]):
            if not w or w.get("kind") != "gun":
                continue
            ammo = w.get("ammo")
            reloading = float(w.get("reload", 0.0) or 0.0)
            ws = self._stats(w)
            mag = int(ws.get("mag", 12))
            if ammo is None or reloading > 0.0:
                break
            shootable = (
                ammo > 0
                and prim_d <= 0.95 * float(ws.get("range", 230.0))
                and clear
                and aligned
            )
            low = ammo <= max(1, int(mag * tuning.ATTACK_RELOAD_FRAC))
            if (ammo <= 0) or (not shootable and low):
                reload_req = True
                slot_ready[i] = max(
                    slot_ready[i], float(ws.get("reload", 2.4))
                )
            break

        next_ready = min(slot_ready) if slot_ready else 1e9
        if next_ready > 1e8:
            next_ready = 1e9
        solution = {
            "aim": aim,
            "fire": (bool(fire[0]), bool(fire[1])),
            "reload": reload_req,
            "next_ready_s": next_ready,
            "down": next_ready > tuning.ATTACK_DOWN_S,
            "hit_prob": hit_prob,
            "d3": d3,
            "clear": clear,
            "aligned": aligned,
            "target_id": t.id if t is not None else None,
        }
        self.last_solution = solution
        return solution

    def idle_reload(self, bf) -> bool:
        """Top up between fights; never while a shot is available."""
        for w in (bf.me.get("weapons") or [])[:2]:
            if not w or w.get("kind") != "gun":
                continue
            ammo = w.get("ammo")
            reloading = float(w.get("reload", 0.0) or 0.0)
            ws = self._stats(w)
            mag = int(ws.get("mag", 12))
            if ammo is not None and reloading <= 0.0:
                return ammo <= max(1, int(mag * tuning.ATTACK_RELOAD_FRAC))
        return False

    def ghost_fire(self, bf, t) -> Optional[Dict[str, Any]]:
        """Return fire at a beam/damage ghost: trees block sight, not shots."""
        if t is None or t.pos is None:
            return None
        if bf.t - (t.last_fire_t if t.last_fire_t is not None else -1e9) > 3.0:
            return None
        me = bf.me
        pos = self._me_pos(bf)
        muzzle = bf.muzzle
        d = dist3(pos, t.pos)
        if d > 120.0:
            return None
        body = (t.pos[0], t.pos[1], t.pos[2] + 4.5)
        if self.los.shot(muzzle, body):
            return None
        yaw = math.atan2(body[1] - pos[1], body[0] - pos[0])
        hd = math.hypot(body[0] - pos[0], body[1] - pos[1])
        pitch = math.atan2(body[2] - muzzle[2], max(0.1, hd))
        self.last_aim = (yaw, pitch)
        fire = [False, False]
        for i, w in enumerate((me.get("weapons") or [])[:2]):
            if w is None or w.get("kind") != "gun":
                continue
            cd = float(w.get("cooldown", 0.0) or 0.0)
            ammo = w.get("ammo")
            reloading = float(w.get("reload", 0.0) or 0.0)
            if ammo is not None and ammo > 0 and cd <= 0.12 and reloading <= 0.0:
                actual = me.get("aim", (0.0, 0.0))
                gate = math.radians(4.0)
                if (abs(angle_diff(float(actual[0]), yaw)) <= gate
                        and abs(float(actual[1]) - pitch) <= gate):
                    fire[i] = True
        return {"aim": (yaw, pitch), "fire": fire, "reload": False}

    def face(self, bf, yaw: float) -> Tuple[float, float]:
        """Keep the last pitch; used when there is no target."""
        self.last_aim = (yaw, self.last_aim[1])
        return self.last_aim
