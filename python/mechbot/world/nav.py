"""Coarse ground-layer walkability and A*."""
from __future__ import annotations

import heapq
import math
from typing import Dict, List, Optional, Sequence, Tuple

from mechbot import tuning
from mechbot.config import Config
from mechbot.world.mapmodel import MapModel

Cell = Tuple[int, int]

_NEIGHBORS = (
    (1, 0, 1.0),
    (-1, 0, 1.0),
    (0, 1, 1.0),
    (0, -1, 1.0),
    (1, 1, 1.41421356),
    (1, -1, 1.41421356),
    (-1, 1, 1.41421356),
    (-1, -1, 1.41421356),
)


class NavGrid:
    def __init__(self, mapmodel: MapModel, cfg: Config):
        self.map = mapmodel
        self.cfg = cfg
        self.cell = tuning.NAV_CELL_M
        self.nx = int(math.ceil((mapmodel.maxx - mapmodel.minx) / self.cell))
        self.ny = int(math.ceil((mapmodel.maxy - mapmodel.miny) / self.cell))
        self.walk = bytearray(self.nx * self.ny)
        self.h = [0.0] * (self.nx * self.ny)
        self._build()
        self._cache: Dict[Tuple[float, float], Tuple[float, float, float, float, List[Tuple[float, float]]]] = {}

    # --- grid ------------------------------------------------------------
    def _build(self) -> None:
        m = self.map
        for j in range(self.ny):
            y = m.miny + (j + 0.5) * self.cell
            for i in range(self.nx):
                x = m.minx + (i + 0.5) * self.cell
                idx = j * self.nx + i
                self.h[idx] = m.height_at(x, y)
                if not m.in_bounds(x, y, 1.0):
                    continue
                if m.ground_blocked(x, y):
                    continue
                self.walk[idx] = 1

    def cell_of(self, x: float, y: float) -> Cell:
        i = int((x - self.map.minx) / self.cell)
        j = int((y - self.map.miny) / self.cell)
        return min(max(i, 0), self.nx - 1), min(max(j, 0), self.ny - 1)

    def center_of(self, c: Cell) -> Tuple[float, float]:
        return (
            self.map.minx + (c[0] + 0.5) * self.cell,
            self.map.miny + (c[1] + 0.5) * self.cell,
        )

    def is_walkable_cell(self, c: Cell) -> bool:
        if c[0] < 0 or c[1] < 0 or c[0] >= self.nx or c[1] >= self.ny:
            return False
        return self.walk[c[1] * self.nx + c[0]] != 0

    def is_walkable(self, x: float, y: float) -> bool:
        return self.map.in_bounds(x, y, 0.5) and not self.map.ground_blocked(x, y)

    def _step_ok(self, a: Cell, b: Cell, diag: bool) -> bool:
        if not self.is_walkable_cell(b):
            return False
        if diag:
            if not self.is_walkable_cell((b[0], a[1])):
                return False
            if not self.is_walkable_cell((a[0], b[1])):
                return False
        ha = self.h[b[1] * self.nx + b[0]]
        hb = self.h[a[1] * self.nx + a[0]]
        dh = ha - hb
        if dh > self.cfg.step_up:
            return False
        if dh > 0.2:
            slope = math.degrees(math.atan2(dh, self.cell))
            if slope > self.cfg.max_slope_deg:
                return False
        return True

    # --- nearest walkable -------------------------------------------------
    def nearest_walkable(self, x: float, y: float, max_rings: int = 10) -> Tuple[float, float]:
        c = self.cell_of(x, y)
        if self.is_walkable_cell(c):
            return self.center_of(c)
        for r in range(1, max_rings + 1):
            best: Optional[Cell] = None
            bestd = 1e30
            for di in range(-r, r + 1):
                for dj in range(-r, r + 1):
                    if max(abs(di), abs(dj)) != r:
                        continue
                    cc = (c[0] + di, c[1] + dj)
                    if not self.is_walkable_cell(cc):
                        continue
                    cx, cy = self.center_of(cc)
                    d = (cx - x) ** 2 + (cy - y) ** 2
                    if d < bestd:
                        bestd = d
                        best = cc
            if best is not None:
                return self.center_of(best)
        return x, y

    # --- A* --------------------------------------------------------------
    def _heuristic(self, a: Cell, b: Cell) -> float:
        dx = abs(a[0] - b[0])
        dy = abs(a[1] - b[1])
        return (dx + dy) + (1.41421356 - 2.0) * min(dx, dy)

    def line_clear(
        self, x: float, y: float, dx: float, dy: float, dist: float, step: float = 3.0
    ) -> bool:
        if dist <= 0.0:
            return True
        n = max(1, int(dist / max(0.5, step)))
        for k in range(1, n + 1):
            t = dist * k / n
            if not self.is_walkable(x + dx * t, y + dy * t):
                return False
        return True

    def path(self, start: Sequence[float], goal: Sequence[float]) -> List[Tuple[float, float]]:
        s = self.cell_of(start[0], start[1])
        g = self.cell_of(goal[0], goal[1])
        if not self.is_walkable_cell(s):
            s = self.cell_of(*self.nearest_walkable(start[0], start[1]))
        if not self.is_walkable_cell(g):
            g = self.cell_of(*self.nearest_walkable(goal[0], goal[1]))
        if s == g:
            return [(float(goal[0]), float(goal[1]))]

        open_heap: List[Tuple[float, int, Cell]] = []
        counter = 0
        weight = 1.6
        h0 = weight * self._heuristic(s, g)
        heapq.heappush(open_heap, (h0, counter, s))
        gscore: Dict[Cell, float] = {s: 0.0}
        came: Dict[Cell, Cell] = {}
        expanded = 0
        while open_heap and expanded < tuning.PATH_NODE_CAP:
            _, _, cur = heapq.heappop(open_heap)
            expanded += 1
            if cur == g:
                break
            base = gscore[cur]
            for dx, dy, cost in _NEIGHBORS:
                nxt = (cur[0] + dx, cur[1] + dy)
                if not self._step_ok(cur, nxt, dx != 0 and dy != 0):
                    continue
                ng = base + cost
                old = gscore.get(nxt)
                if old is not None and ng >= old - 1e-9:
                    continue
                gscore[nxt] = ng
                came[nxt] = cur
                counter += 1
                heapq.heappush(open_heap, (ng + weight * self._heuristic(nxt, g), counter, nxt))

        if g not in gscore:
            return [(float(start[0]), float(start[1])), (float(goal[0]), float(goal[1]))]

        cells: List[Cell] = [g]
        cur = g
        while cur != s:
            cur = came[cur]
            cells.append(cur)
        cells.reverse()
        pts: List[Tuple[float, float]] = []
        for c in cells[1:]:
            pts.append(self.center_of(c))
        if not pts:
            pts.append((float(goal[0]), float(goal[1])))
        return pts

    def path_cached(
        self, start: Sequence[float], goal: Sequence[float], force: bool = False
    ) -> List[Tuple[float, float]]:
        key = (float(goal[0]), float(goal[1]))
        hit = self._cache.get(key)
        if hit is not None and not force:
            sx, sy, gx, gy, pts = hit
            if (
                (sx - start[0]) ** 2 + (sy - start[1]) ** 2 < 64.0
                and (gx - key[0]) ** 2 + (gy - key[1]) ** 2 < 25.0
            ):
                return pts
        pts = self.path(start, goal)
        self._cache[key] = (float(start[0]), float(start[1]), key[0], key[1], pts)
        if len(self._cache) > 24:
            self._cache.pop(next(iter(self._cache)))
        return pts

    def path_length(self, path: Sequence[Sequence[float]], start: Sequence[float]) -> float:
        total = 0.0
        px, py = start[0], start[1]
        for p in path:
            total += math.hypot(p[0] - px, p[1] - py)
            px, py = p[0], p[1]
        return total

    # --- local probes -----------------------------------------------------
    def local_clear(self, x: float, y: float, dx: float, dy: float, dist: float) -> bool:
        n = max(1, int(dist / 1.0))
        for k in range(1, n + 1):
            t = k / n
            if not self.is_walkable(x + dx * dist * t, y + dy * dist * t):
                return False
        return True
