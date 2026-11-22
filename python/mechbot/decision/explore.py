"""Explore filler: walk unvisited ground along the rotation corridor.

With a 200 m / 120 deg view wedge and 40 floor pickups over 770 000 m^2, a bot
that stands still finds nothing; one live match saw a single pickup in 962 m.
The grid is coarse (60 m cells) and the goal is biased toward the next circle,
so a patrol is free rotation rather than a detour.

Only cells the roadmap can serve are candidates: the snapped node must be close
and on the main component, otherwise the cell is inside a building or a hole.
"""
from __future__ import annotations

import math
from typing import Dict, Optional, Sequence, Tuple

from mechbot import tuning

Cell = Tuple[int, int]


class ExplorePlanner:
    def __init__(self, cfg, road, field):
        self.cfg = cfg
        self.road = road
        self.field = field
        self.size = max(20.0, float(tuning.EXPLORE_CELL_M))
        if road is not None and road.n > 0:
            self.x0 = min(road.x) - self.size
            self.y0 = min(road.y) - self.size
            self.nx = int((max(road.x) - self.x0) / self.size) + 2
            self.ny = int((max(road.y) - self.y0) / self.size) + 2
        else:
            self.x0 = self.y0 = -600.0
            self.nx = self.ny = 24
        self.visited: Dict[Cell, float] = {}
        self.goal: Optional[Tuple[float, float]] = None
        self.goal_t = -1e9
        self.goal_cell: Optional[Cell] = None
        self.reason = ""

    # --- grid ---------------------------------------------------------
    def cell(self, x: float, y: float) -> Cell:
        return (int((x - self.x0) / self.size), int((y - self.y0) / self.size))

    def centre(self, c: Cell) -> Tuple[float, float]:
        return (self.x0 + (c[0] + 0.5) * self.size,
                self.y0 + (c[1] + 0.5) * self.size)

    def mark(self, x: float, y: float, now: float) -> None:
        self.visited[self.cell(x, y)] = now

    # --- selection ----------------------------------------------------
    def update(self, bf, now: float):
        """Mark the current cell and refresh the goal when it is stale."""
        me = bf.me
        pos = me.get("pos", (0.0, 0.0, 0.0))
        self.mark(pos[0], pos[1], now)
        if not tuning.EXPLORE_ENABLE:
            return None
        if (self.goal is not None and now - self.goal_t < tuning.EXPLORE_HOLD_S
                and math.hypot(self.goal[0] - pos[0], self.goal[1] - pos[1])
                > tuning.EXPLORE_ARRIVE_M):
            return self.goal
        goal = self._pick(bf, pos, now)
        if goal is None:
            self.goal = None
            self.goal_cell = None
            self.reason = "none"
            return None
        self.goal = goal
        self.goal_t = now
        self.reason = "cell %d,%d" % self.goal_cell
        return self.goal

    def _pick(self, bf, pos, now: float):
        zone = bf.zone
        nc = zone.get("next_center", (0.0, 0.0))
        nr = float(zone.get("next_radius", 0.0))
        shrink_end = float(zone.get("shrink_end", 0.0))
        dirn = (0.0, 0.0)
        dx, dy = nc[0] - pos[0], nc[1] - pos[1]
        d = math.hypot(dx, dy)
        if d > 1e-6:
            dirn = (dx / d, dy / d)
        best = None
        best_score = -1e18
        for i in range(self.nx):
            for j in range(self.ny):
                c = (i, j)
                if c in self.visited:
                    continue
                cx, cy = self.centre(c)
                if nr > 1.0 and math.hypot(cx - nc[0], cy - nc[1]) > max(20.0, nr - 8.0):
                    continue
                dc = math.hypot(cx - pos[0], cy - pos[1])
                if dc > tuning.EXPLORE_RADIUS_M or dc < tuning.EXPLORE_MIN_M:
                    continue
                k = self.road.snap(cx, cy)
                if k < 0 or self.road.comp[k] != self.road.main:
                    continue
                if math.hypot(self.road.x[k] - cx, self.road.y[k] - cy) > 25.0:
                    continue
                if not self._zone_ok(bf, (cx, cy), now, dc):
                    continue
                ux, uy = (cx - pos[0]) / max(1e-6, dc), (cy - pos[1]) / max(1e-6, dc)
                ahead = ux * dirn[0] + uy * dirn[1]
                # nearer is better, but do not walk backwards against the
                # rotation unless there is nothing in front
                score = -dc + tuning.EXPLORE_AHEAD_M * ahead
                if best is None or score > best_score:
                    best, best_score = c, score
        if best is None:
            return None
        self.goal_cell = best
        return self.centre(best)

    def _zone_ok(self, bf, p, now: float, dist: float) -> bool:
        field = self.field
        if field is None or not getattr(field, "eta", None):
            return True
        try:
            eta = dist * 1.25 / max(1.0, float(self.cfg.walk_speed)) + 5.0
            dl = field.deadline(bf.zone, p, now)
        except Exception:  # noqa: BLE001 - field is optional in tests
            return True
        return now + eta <= dl - tuning.EXPLORE_ZONE_MARGIN_S
