"""Map-scale belief about where the enemies we cannot see are, weighted by power.

A count field is not enough: four gun-only mechs at half HP is a fight we win,
two laser carriers at full HP is not. So every component carries
`expected hostile DPS` as well as a head count, and consumers ask for power.

Sources, in order of trust:

1. observed mechs -- sharp kernel, position extrapolated along velocity, kernel
   width growing with age;
2. sound contacts and damage bearings -- a ray in the bearing, distance prior
   from the `near/mid/far` bucket;
3. loot attractors -- enemies also loot, so remembered crates/pickups pull mass;
4. the zone prior -- everyone must rotate, so the unseen mass sits mostly in
   the next circle. This is the only component that is always true.

The total head count is normalised to `alive - 1` (ourselves excluded), so the
field cannot invent or lose enemies. Rebuilds are cheap (25 m cells,
~1 200 cells) and run at most every 0.4 s.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from mechbot import tuning
from mechbot import power as st
from mechbot.geometry import angle_diff, bearing

Vec2 = Tuple[float, float]

DIST_BUCKET = {"near": 40.0, "mid": 110.0, "far": 240.0}


class StrengthField:
    def __init__(self, cfg, road, walk_speed: float = 11.7):
        self.cfg = cfg
        self.size = max(10.0, float(tuning.STR_CELL_M))
        self.walk = max(1.0, walk_speed)
        if road is not None and road.n > 0:
            self.x0 = min(road.x) - 4 * self.size
            self.y0 = min(road.y) - 4 * self.size
            self.nx = int((max(road.x) - self.x0) / self.size) + 2
            self.ny = int((max(road.y) - self.y0) / self.size) + 2
        else:
            self.x0 = self.y0 = -600.0
            self.nx = self.ny = 48
        n = self.nx * self.ny
        self.power = [0.0] * n
        self.count = [0.0] * n
        self.total_power = 0.0
        self.total_count = 0.0
        self.unseen = 0.0
        self.t = -1e9
        self.built = 0
        self._prior_key = None
        self._prior: List[float] = []

    # --- geometry -----------------------------------------------------
    def _idx(self, x: float, y: float) -> int:
        i = int((x - self.x0) / self.size)
        j = int((y - self.y0) / self.size)
        if i < 0 or j < 0 or i >= self.nx or j >= self.ny:
            return -1
        return j * self.nx + i

    def at(self, x: float, y: float) -> float:
        k = self._idx(x, y)
        return 0.0 if k < 0 else self.power[k]

    def count_at(self, x: float, y: float) -> float:
        k = self._idx(x, y)
        return 0.0 if k < 0 else self.count[k]

    def path_risk(self, a: Sequence[float], b: Sequence[float],
                  step: float = 15.0) -> float:
        """Power integrated along a straight line, in dps * cells."""
        dx, dy = b[0] - a[0], b[1] - a[1]
        d = math.hypot(dx, dy)
        if d < 1e-6:
            return self.at(a[0], a[1]) * self.size
        n = max(1, int(d / step))
        acc = 0.0
        for i in range(n + 1):
            u = i / float(n)
            x = a[0] + dx * u
            y = a[1] + dy * u
            acc += self.at(x, y) * step
        return acc

    def mean_near(self, p: Sequence[float], radius: float = 120.0) -> float:
        """Mean power per cell inside `radius` of p (coarse, cheap)."""
        r = max(self.size, radius)
        k = max(1, int(r / self.size))
        i0 = int((p[0] - self.x0) / self.size)
        j0 = int((p[1] - self.y0) / self.size)
        total, cells = 0.0, 0
        for j in range(max(0, j0 - k), min(self.ny, j0 + k + 1)):
            for i in range(max(0, i0 - k), min(self.nx, i0 + k + 1)):
                cx = self.x0 + (i + 0.5) * self.size
                cy = self.y0 + (j + 0.5) * self.size
                if (cx - p[0]) ** 2 + (cy - p[1]) ** 2 > r * r:
                    continue
                total += self.power[j * self.nx + i]
                cells += 1
        return total / cells if cells else 0.0

    # --- build --------------------------------------------------------
    def due(self, now: float, force: bool = False) -> bool:
        return force or now - self.t >= tuning.STR_REBUILD_S

    def rebuild(self, bf, now: float) -> None:
        self.t = now
        self.built += 1
        n = len(self.count)
        self.power = [0.0] * n
        self.count = [0.0] * n
        alive = float(getattr(bf, "alive", 16) or 16)
        mechs = [t for t in bf.tracks.values()
                 if t.kind == "mech" and not t.dead and t.pos is not None]
        observed_mass = 0.0
        for t in mechs:
            observed_mass += self._add_track(t, now)
        sounds = self._add_contacts(bf, now)
        loot = self._add_loot(bf, now)
        unknown = max(0.0, alive - 1.0 - observed_mass)
        self.unseen = unknown
        pc = self._class_power(now)
        self._add_zone(bf, now, unknown, pc)
        self._add_loot_prior(loot, pc)
        self._rescale(alive - 1.0)
        self._totals()

    # --- components ---------------------------------------------------
    def _add_track(self, t, now: float) -> float:
        age = max(0.0, now - t.last_listed_t)
        if age > tuning.STR_TRACK_TTL_S:
            return 0.0
        w = math.exp(-age / tuning.STR_DECAY_S)
        pos = t.pos
        if t.vel is not None and age > 0.0:
            u = min(age, 3.0)
            pos = (pos[0] + float(t.vel[0]) * u,
                   pos[1] + float(t.vel[1]) * u)
        hp_frac = t.hp_frac if t.hp_frac is not None else 0.75
        p = st.power(self.cfg, hp_frac, int(t.cubes or 0),
                     t.weapons or ("gun",), 80.0)
        sigma = tuning.STR_TRACK_SIGMA_M + tuning.STR_AGE_SIGMA_M * age
        self._kernel(pos[0], pos[1], sigma, w, p * w)
        return w

    def _add_contacts(self, bf, now: float) -> None:
        me = bf.me.get("pos", (0.0, 0.0, 0.0))
        for c in getattr(bf, "contacts", ()) or ():
            age = now - c.t
            if age < 0.0 or age > tuning.STR_CONTACT_TTL_S:
                continue
            d0 = DIST_BUCKET.get(c.dist, 160.0)
            w = 0.7 * math.exp(-age / tuning.STR_DECAY_S)
            self._ray(me, c.bearing, d0, w, self._class_power(now) * w)
        brg = bf.last_damage_bearing(tuning.STR_DAMAGE_AGE_S)
        if brg is not None:
            self._ray(me, brg, 120.0, 1.0, self._class_power(now))

    def _add_loot(self, bf, now: float) -> float:
        items = getattr(bf, "items", None)
        if items is None:
            return 0.0
        me = bf.me.get("pos", (0.0, 0.0, 0.0))
        cand = []
        for it in items.items.values():
            age = now - it.last_seen_t
            if age > 30.0:
                continue
            d = math.hypot(it.pos[0] - me[0], it.pos[1] - me[1])
            if d > 260.0:
                continue
            cand.append((d, age, it))
        cand.sort(key=lambda x: x[0])
        got = 0.0
        pc = self._class_power(now)
        for d, age, it in cand[:tuning.STR_LOOT_MAX_ITEMS]:
            w = min(0.5, 0.5 * math.exp(-age / 30.0))
            got += w
            self._kernel(it.pos[0], it.pos[1], tuning.STR_LOOT_SIGMA_M, w, pc * w)
        return min(got, 3.0)

    def _add_zone(self, bf, now: float, mass: float, pc: float) -> None:
        if mass <= 0.0:
            return
        zone = bf.zone
        nc = zone.get("next_center", (0.0, 0.0))
        nr = max(1.0, float(zone.get("next_radius", 0.0)))
        cc = zone.get("center", (0.0, 0.0))
        cr = max(1.0, float(zone.get("radius", 0.0)))
        key = (round(nc[0]), round(nc[1]), round(nr),
               round(cc[0]), round(cc[1]), round(cr))
        if key != self._prior_key or len(self._prior) != len(self.count):
            # the prior only changes when the circle does, so build it once
            sigma = max(20.0, tuning.STR_ZONE_SIGMA_FRAC * nr)
            prior = [0.0] * len(self.count)
            total = 0.0
            k = 0
            for j in range(self.ny):
                for i in range(self.nx):
                    cx = self.x0 + (i + 0.5) * self.size
                    cy = self.y0 + (j + 0.5) * self.size
                    d1 = math.hypot(cx - nc[0], cy - nc[1])
                    w = tuning.STR_ZONE_NEXT * math.exp(-(d1 / sigma) ** 2)
                    if d1 <= cr:
                        w += tuning.STR_ZONE_RING
                    prior[k] = w
                    total += w
                    k += 1
            if total > 0.0:
                prior = [w / total for w in prior]
            self._prior = prior
            self._prior_key = key
        if not self._prior:
            return
        pcw = pc * mass
        if mass == 0.0:
            return
        if pcw == 0.0:
            self.count = [c + w * mass for c, w in zip(self.count, self._prior)]
            return
        self.count = [c + w * mass for c, w in zip(self.count, self._prior)]
        self.power = [p + w * pcw for p, w in zip(self.power, self._prior)]

    def _add_loot_prior(self, mass: float, pc: float) -> None:
        """Small extra mass where loot was seen (already added by _add_loot)."""
        return

    def _rescale(self, target_count: float) -> None:
        total = sum(self.count)
        if total <= 1e-9:
            return
        scale = max(0.0, target_count) / total
        if abs(scale - 1.0) > 1e-6:
            self.count = [c * scale for c in self.count]
            self.power = [p * scale for p in self.power]
            total *= scale
        self.total_count = sum(self.count)
        self.total_power = sum(self.power)

    def _totals(self) -> None:
        return

    def _class_power(self, now: float) -> float:
        """Mean hostile DPS, ramping as the field arms itself."""
        base = tuning.STR_CLASS_POWER
        return base + tuning.STR_CLASS_RAMP * min(1.0, now / 90.0)

    # --- kernels ------------------------------------------------------
    def _kernel(self, x: float, y: float, sigma: float, w: float,
                p: float) -> None:
        sigma = max(self.size * 0.5, sigma)
        r = 2.5 * sigma
        k = int(r / self.size) + 1
        i0 = int((x - self.x0) / self.size)
        j0 = int((y - self.y0) / self.size)
        two_s2 = 2.0 * sigma * sigma
        for j in range(max(0, j0 - k), min(self.ny, j0 + k + 1)):
            for i in range(max(0, i0 - k), min(self.nx, i0 + k + 1)):
                cx = self.x0 + (i + 0.5) * self.size
                cy = self.y0 + (j + 0.5) * self.size
                d2 = (cx - x) ** 2 + (cy - y) ** 2
                if d2 > r * r:
                    continue
                g = math.exp(-d2 / two_s2)
                self.count[j * self.nx + i] += w * g
                self.power[j * self.nx + i] += p * g

    def _ray(self, origin, brg: float, d0: float, w: float, p: float) -> None:
        """Bearing + distance prior: a limb of the map, not a point.

        Painted by marching along the bearing and dropping a small cross at
        each step; the gaussian is evaluated in the angular/distance domain,
        not per cell, which keeps a rebuild under a millisecond.
        """
        rmax = min(d0 + 3.0 * tuning.STR_RAY_SIGMA_M, 320.0)
        rmin = max(self.size, d0 - 3.0 * tuning.STR_RAY_SIGMA_M)
        if rmax <= rmin:
            return
        ux, uy = math.cos(brg), math.sin(brg)
        step = self.size
        n = max(1, int((rmax - rmin) / step))
        for i in range(n + 1):
            d = rmin + (rmax - rmin) * i / n
            g = math.exp(-((d - d0) / tuning.STR_RAY_SIGMA_M) ** 2)
            if g < 0.05:
                continue
            k = self._idx(origin[0] + ux * d, origin[1] + uy * d)
            if k < 0:
                continue
            j, ii = divmod(k, self.nx)
            for dj in (-1, 0, 1):
                jj = j + dj
                if jj < 0 or jj >= self.ny:
                    continue
                for di in (-1, 0, 1):
                    iii = ii + di
                    if iii < 0 or iii >= self.nx:
                        continue
                    kk = jj * self.nx + iii
                    self.count[kk] += w * g
                    self.power[kk] += p * g
