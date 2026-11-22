"""Zone margin: ETA field, deadline and slack."""
from __future__ import annotations

import heapq
import math
from typing import Dict, List, Optional, Sequence, Tuple

MARGIN_M = 8.0


class Field:
    def __init__(self, road, walk_speed: float = 11.7):
        self.road = road
        self.speed = max(1.0, walk_speed)
        self.eta: Optional[List[float]] = None
        self.next: Optional[List[int]] = None
        self.key: Tuple = ()
        self._heap: list = []
        self.center: Tuple[float, float] = (0.0, 0.0)
        self.radius = 0.0

    # --- build (time-sliced) ------------------------------------------
    def ensure(self, zone: dict, center: Sequence[float], radius: float,
               budget: float = 0.0015) -> None:
        key = self._key(zone)
        moved = math.hypot(center[0] - self.center[0], center[1] - self.center[1]) > 5.0
        if self.eta is None or key != self.key or moved:
            self._start(zone, center, radius)
        if self._heap:
            self._advance(budget)

    def build(self, zone: dict, center: Sequence[float], radius: float) -> None:
        self._start(zone, center, radius)
        self._advance(1e9)

    @staticmethod
    def _key(zone: dict) -> Tuple:
        nc = zone.get("next_center", (0.0, 0.0))
        return (
            round(float(zone.get("shrink_start", 0.0)), 2),
            round(float(zone.get("shrink_end", 0.0)), 2),
            round(float(zone.get("next_radius", 0.0)), 2),
            round(float(nc[0]), 1),
            round(float(nc[1]), 1),
        )

    def _start(self, zone, center, radius) -> None:
        road = self.road
        n = road.n
        seeds = []
        r = radius
        cx, cy = float(center[0]), float(center[1])
        while r > 1.0:
            r2 = r * r
            seeds = [
                k for k in range(n)
                if (road.x[k] - cx) ** 2 + (road.y[k] - cy) ** 2 <= r2
            ]
            main = [k for k in seeds if road.comp[k] == road.main]
            if len(main) >= 4:
                seeds = main
                break
            if len(seeds) >= 4:
                break
            r *= 1.25
        eta = [1e18] * n
        nxt = [-1] * n
        heap = []
        for k in seeds:
            eta[k] = 0.0
            nxt[k] = k
        heap = [(0.0, k) for k in seeds]
        heapq.heapify(heap)
        self.eta, self.next = eta, nxt
        self._heap = heap
        self.center = (cx, cy)
        self.radius = float(radius)
        self.key = self._key(zone)

    def _advance(self, budget: float) -> None:
        import time as _t

        t_end = _t.perf_counter() + budget
        eta, nxt, heap = self.eta, self.next, self._heap
        off, dst, ln = self.road.off, self.road.dst, self.road.length
        while heap:
            du, u = heapq.heappop(heap)
            if du > eta[u] + 1e-6:
                continue
            for e in range(off[u], off[u + 1]):
                v = dst[e]
                nd = du + ln[e]
                if nd + 1e-6 < eta[v]:
                    eta[v] = nd
                    nxt[v] = u
                    heapq.heappush(heap, (nd, v))
            if _t.perf_counter() >= t_end:
                break

    def stale(self, zone: dict, center: Sequence[float], radius: float) -> bool:
        if self.eta is None:
            return True
        if self._key(zone) != self.key:
            return True
        return math.hypot(center[0] - self.center[0], center[1] - self.center[1]) > 5.0

    @property
    def busy(self) -> bool:
        return bool(self._heap)

    # --- queries ------------------------------------------------------
    def node_eta(self, k: int) -> float:
        if self.eta is None or k < 0:
            return 1e9
        return self.eta[k]

    def eta_at(self, x: float, y: float) -> float:
        k = self.road.snap(x, y)
        if k < 0 or self.eta is None:
            return 1e9
        d = math.hypot(self.road.x[k] - x, self.road.y[k] - y)
        if self.eta[k] > 1e8:
            # sliced build has not reached this node yet: straight-line guess
            return math.hypot(x - self.center[0], y - self.center[1]) / self.speed
        return (self.eta[k] + d) / self.speed

    def next_point(self, x: float, y: float) -> Tuple[float, float]:
        k = self.road.snap(x, y)
        if k < 0 or self.next is None:
            return (x, y)
        v = self.next[k]
        if v < 0:
            # not settled yet: head straight for the seeded centre
            dx, dy = self.center[0] - x, self.center[1] - y
            d = math.hypot(dx, dy)
            if d < 1e-6:
                return (x, y)
            step = min(12.0, d)
            return (x + dx / d * step, y + dy / d * step)
        return (self.road.x[v], self.road.y[v])

    def deadline(self, zone: dict, p: Sequence[float], now: float, margin: float = MARGIN_M) -> float:
        c0 = zone.get("center", (0.0, 0.0))
        c1 = zone.get("next_center", c0)
        r0 = float(zone.get("radius", 0.0))
        r1 = float(zone.get("next_radius", r0))
        t0 = float(zone.get("shrink_start", 0.0))
        t1 = float(zone.get("shrink_end", 0.0))
        if t1 <= t0:
            return now + 3600.0
        if r1 <= 0.5:
            return t1
        if now < t0:
            if math.hypot(p[0] - c1[0], p[1] - c1[1]) <= max(0.0, r1 - margin):
                return t1
            return t0
        if now >= t1:
            return now
        # During a shrink, obs gives the *current* radius/centre, not the
        # phase-start values, so interpolate from (now, r0) to (t1, r1).
        span = max(1e-6, t1 - now)
        prev = now
        for i in range(1, 21):
            u = i / 20.0
            t = now + span * u
            cx = c0[0] + (c1[0] - c0[0]) * u
            cy = c0[1] + (c1[1] - c0[1]) * u
            rr = r0 + (r1 - r0) * u
            inside = math.hypot(p[0] - cx, p[1] - cy) <= max(0.0, rr - margin)
            if not inside:
                return prev
            prev = t
        return t1

    def slack(self, zone: dict, p: Sequence[float], now: float) -> float:
        return self.deadline(zone, p, now) - now - self.eta_at(p[0], p[1])
