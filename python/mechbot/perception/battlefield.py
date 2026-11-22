"""Read-only per-tick view consumed by the mode machine."""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from mechbot.config import Config
from mechbot.geometry import (
    angle_diff,
    bearing,
    clamp,
    dist2,
    dist3,
    dot2,
    point_segment_distance,
)
from mechbot.perception.model import AgentTrack, Contact


class Battlefield:
    def __init__(
        self,
        t: float,
        tick: float,
        me: Dict[str, Any],
        zone: Dict[str, Any],
        tracks: Dict[int, AgentTrack],
        contacts: List[Contact],
        projectiles: List[Dict[str, Any]],
        los,
        cfg: Config,
        last_damage_bearing: Optional[float],
        last_damage_t: float,
        last_damage_weapon: Optional[str],
        items=None,
        offer: Optional[Dict[str, Any]] = None,
        alive: int = 16,
    ):
        self.t = t
        self.tick = tick
        self.me = me
        self.zone = zone
        self.tracks = tracks
        self.contacts = contacts
        self.projectiles = projectiles
        self.los = los
        self.mapmodel = los
        self.cfg = cfg
        self._last_damage_bearing = last_damage_bearing
        self._last_damage_t = last_damage_t
        self._last_damage_weapon = last_damage_weapon
        self.items = items
        self.offer = offer
        self.alive = alive
        self.last_damage_t = last_damage_t

    # --- agents ----------------------------------------------------------
    def agents(self) -> Iterable[AgentTrack]:
        return self.tracks.values()

    def enemies(self, status: Optional[str] = None) -> List[AgentTrack]:
        out = [a for a in self.tracks.values() if a.kind == "mech" and not a.dead]
        if status is not None:
            out = [a for a in out if a.status == status]
        return out

    def track(self, ident: Optional[int]) -> Optional[AgentTrack]:
        if ident is None:
            return None
        return self.tracks.get(int(ident))

    def targetable(self, track: Optional[AgentTrack]) -> bool:
        return bool(
            track is not None
            and track.kind == "mech"
            and not track.dead
            and track.pos is not None
            and track.status == "visible"
        )

    def attacker_since(self, max_age_s: float) -> Optional[AgentTrack]:
        best: Optional[AgentTrack] = None
        bt = -1e9
        for a in self.tracks.values():
            if a.last_damaged_us_t is None:
                continue
            if self.t - a.last_damaged_us_t <= max_age_s and a.last_damaged_us_t > bt:
                best = a
                bt = a.last_damaged_us_t
        return best

    def last_damage_bearing(self, max_age_s: float = 2.0) -> Optional[float]:
        if self._last_damage_bearing is None:
            return None
        if self.t - self._last_damage_t > max_age_s:
            return None
        if self._last_damage_weapon in ("zone", "npc"):
            return None
        return self._last_damage_bearing

    def nearest_visible(self, max_dist: float) -> Optional[AgentTrack]:
        best: Optional[AgentTrack] = None
        bd = max_dist * max_dist
        for a in self.enemies("visible"):
            if a.pos is None:
                continue
            d = dist2(self.me["pos"], a.pos)
            if d < bd:
                bd = d
                best = a
        return best

    # --- geometry --------------------------------------------------------
    @property
    def muzzle(self) -> Tuple[float, float, float]:
        p = self.me["pos"]
        stats = self.me.get("stats") or {}
        return (p[0], p[1], p[2] + float(stats.get("muzzle_height", self.cfg.muzzle_height)))

    def lead_point(
        self, track: AgentTrack, speed: float, extra_t: float = 0.1
    ) -> Optional[Tuple[float, float, float]]:
        if track.pos is None or track.vel is None:
            return None
        cubes = track.cubes or 0
        scale = 1.0 + self.cfg.size_per_cube * cubes
        t = max(0.0, extra_t)
        return (
            track.pos[0] + track.vel[0] * t,
            track.pos[1] + track.vel[1] * t,
            track.pos[2] + 0.5 * self.cfg.height * scale + track.vel[2] * t,
        )

    def shot_clear(
        self, track: Optional[AgentTrack], aim_point: Sequence[float]
    ) -> bool:
        if track is None or track.pos is None:
            return False
        return not self.los.shot(self.muzzle, aim_point)

    def _in_zone(self, p: Sequence[float]) -> bool:
        z = self.zone
        c = z.get("center", (0.0, 0.0))
        r = float(z.get("radius", 0.0))
        return dist2(p, c) <= r

    def incoming(self, horizon_s: float = 1.5) -> List[Dict[str, Any]]:
        me = self.me["pos"]
        radius = float((self.me.get("stats") or {}).get("radius", self.cfg.radius)) + 0.5
        height = float((self.me.get("stats") or {}).get("height", self.cfg.height))
        out: List[Dict[str, Any]] = []
        for pr in self.projectiles:
            pos = pr.get("pos")
            vel = pr.get("vel")
            if not pos or not vel:
                continue
            kind = pr.get("kind")
            g = float(self.cfg.weapon("mortar").get("gravity", 22.0)) if kind == "mortar" else 0.0
            x, y, z = float(pos[0]), float(pos[1]), float(pos[2])
            vx, vy, vz = float(vel[0]), float(vel[1]), float(vel[2])
            best_t = 0.0
            best_miss = 1e30
            steps = max(1, int(horizon_s / 0.05))
            for k in range(1, steps + 1):
                dt = k * 0.05
                px = x + vx * dt
                py = y + vy * dt
                pz = z + vz * dt - 0.5 * g * dt * dt
                if pz < me[2] - 1.0:
                    break
                dxy = math.hypot(px - me[0], py - me[1])
                if dxy <= radius and me[2] - 0.5 <= pz <= me[2] + height:
                    if dt < best_miss:
                        best_t, best_miss = dt, 0.0
                    break
                if dxy < best_miss:
                    best_miss = dxy
                    best_t = dt
                if dt >= horizon_s:
                    break
            if best_miss < 1e29:
                out.append({"t": best_t, "miss": best_miss, "kind": kind})
        out.sort(key=lambda d: d["t"])
        return out

    def danger_from(self, track: Optional[AgentTrack]) -> Optional[Dict[str, Any]]:
        if track is None or not track.charging or track.pos is None or track.aim is None:
            return None
        cubes = track.cubes or 0
        scale = 1.0 + self.cfg.size_per_cube * cubes
        mz = track.pos[2] + self.cfg.muzzle_height * scale
        yaw = float(track.aim[0])
        rng = float(self.cfg.weapon("laser").get("range", 280.0))
        a = (track.pos[0], track.pos[1], mz)
        b = (track.pos[0] + math.cos(yaw) * rng, track.pos[1] + math.sin(yaw) * rng, mz)
        me = self.me["pos"]
        d, tt = point_segment_distance(me[0], me[1], a[0], a[1], b[0], b[1])
        if d <= self.cfg.radius + 1.5:
            return {"dist": d, "t": tt}
        return None

    @property
    def armor_known(self) -> bool:
        return False
