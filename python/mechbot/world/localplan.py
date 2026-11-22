"""L2 local planner: refined 2 m window with a coarse exposure field.

Two resolutions on purpose:
  * the A* grid is 2 m over 32 m (17x17 = 289 cells), so doorways, bridge
    piers and thin building faces are represented instead of being averaged
    into 6 m cells, without paying for a 625-cell search on a 1-CPU box;
  * the threat-exposure term is sampled on an 8 m grid (5x5 = 25 rays) and
    bilinearly interpolated, which keeps the ray count affordable in Python
    while leaving the routing resolution at 2 m.
"""
from __future__ import annotations

import heapq
import math
from typing import List, Optional, Sequence, Tuple

from mechbot.geometry import normalize2

CELL = 2.0
HALF = 8
SIZE = HALF * 2 + 1
EXP_M = 8.0
EXP_HALF = 2
EXP_N = EXP_HALF * 2 + 1
W_INF = 1e6

W_WALL = 1.0
W_SLOPE = 0.5
W_EXP = 0.15
W_VIS = 2.5
W_ZONE = 10.0
W_AIR = 4.0
class LocalPlan:
    def __init__(self, st, los, field, walk_speed: float = 11.7):
        self.st = st
        self.los = los
        self.field = field
        self.speed = max(1.0, walk_speed)
        lay = st.layers
        self.stand = lay["standable"]
        self.floor = lay["floor"]
        self.clear = lay["clear"]
        self.wall = lay["wall"]
        self.head = lay["head"]
        self.nx2 = int(st.meta["nx2"])
        self.ny2 = int(st.meta["ny2"])
        self.ground = st.occ["ground"]
        self.top = st.occ["top"]
        self.base = st.occ["base"]
        self.cov = st.occ["cov"]
        self.free_g = st.occ["free_g"]
        self.free_r = st.occ["free_r"]
        self.nx1 = int(st.meta["nx"])
        self.ny1 = int(st.meta["ny"])
        self.minx = st.min_x
        self.miny = st.min_y

    # --- static layer queries -----------------------------------------
    def floor_at(self, x: float, y: float, z: Optional[float] = None) -> Optional[float]:
        """Standable surface of the **1 m** cell containing (x, y).

        Used for the robot's own position and for movement probes: `free_g` is
        already eroded by the mech radius, so no extra 2 m block test is needed.
        """
        i = int(x - self.minx)
        j = int(y - self.miny)
        if i < 0 or j < 0 or i >= self.nx1 or j >= self.ny1:
            return None
        k = j * self.nx1 + i
        lim = (z + 1.2) if z is not None else None
        if self.free_g[k]:
            g = self.ground[k] * 0.01
            if lim is None or g <= lim:
                return g
        if self.free_r[k]:
            t = self.top[k] * 0.01
            if lim is None or t <= lim:
                return t
        return None

    def cell_floor(self, x: float, y: float, z: Optional[float] = None) -> Optional[float]:
        """Standable surface at (x, y) reachable from height z.

        A bridge deck with less than 9 m of clearance is a **wall** for a mech
        under it and a floor for a mech on it; the surface choice therefore
        depends on z, not on the cell alone.
        """
        i0 = int(x - self.minx)
        j0 = int(y - self.miny)
        lim = (z + 1.2) if z is not None else None
        out = None
        # a 2 m cell is free only if all four 1 m children are free: the
        # over-approximation is what keeps the path collision-free
        for di, dj in ((0, 0), (1, 0), (0, 1), (1, 1)):
            i, j = i0 + di, j0 + dj
            if i < 0 or j < 0 or i >= self.nx1 or j >= self.ny1:
                return None
            k = j * self.nx1 + i
            surf = None
            if self.free_g[k]:
                g = self.ground[k] * 0.01
                if lim is None or g <= lim:
                    surf = g
            if surf is None and self.free_r[k]:
                t = self.top[k] * 0.01
                if lim is None or t <= lim:
                    surf = t
            if surf is None:
                return None
            out = surf if out is None else max(out, surf)
        return out

    def standable(self, x: float, y: float, z: Optional[float] = None) -> bool:
        return self.floor_at(x, y, z) is not None

    def clearance(self, x: float, y: float) -> int:
        i = int((x - self.st.min_x) * 0.5)
        j = int((y - self.st.min_y) * 0.5)
        if i < 0 or j < 0 or i >= self.nx2 or j >= self.ny2:
            return 0
        return int(self.clear[j * self.nx2 + i])

    # --- local goal planning -------------------------------------------
    def exposure_at(self, x: float, y: float, z: float,
                    threats: Sequence[Tuple[float, float, float, float, float]],
                    hard: bool = False):
        """(weighted dps, weighted shooter count) that can see this cell."""
        f = self.cell_floor(x, y, z)
        if f is None:
            return 0.0, 0.0
        body = (x, y, f + 4.5)
        top = (x, y, f + 8.8)
        dps = 0.0
        nvis = 0.0
        for tx, ty, tz, tdps, tw in threats:
            eye = (tx, ty, tz + 8.0)
            if (not self.los.fast(eye, body)) or (hard and not self.los.fast(eye, top)):
                nvis += tw
                d = math.hypot(tx - x, ty - y)
                dps += tw * (tdps if d < 200.0 else tdps * 0.25)
        return dps, nvis

    def plan(
        self,
        x: float,
        y: float,
        z: float,
        goal: Sequence[float],
        threats: Sequence[Tuple[float, float, float, float, float]],
        zone: dict,
        now: float,
        hard: bool = False,
    ) -> List[Tuple[float, float, float, int]]:
        if self.standable(x, y, z) is False:
            return []

        # window centred on the bot, goal clamped to the window edge
        base_i = max(-HALF, min(HALF, int(round((goal[0] - x) / CELL))))
        base_j = max(-HALF, min(HALF, int(round((goal[1] - y) / CELL))))
        ox, oy = x, y
        si = sj = HALF
        gi, gj = HALF + base_i, HALF + base_j

        # every known threat contributes, weighted by how dangerous it is;
        # a rival that cannot see us now still covers cells we could walk into
        contacts = threats[:4]

        # coarse exposure + zone field, bilinear for the 2 m grid
        exp = [[0.0] * EXP_N for _ in range(EXP_N)]
        for ej in range(EXP_N):
            for ei in range(EXP_N):
                cx = x + (ei - EXP_HALF) * EXP_M
                cy = y + (ej - EXP_HALF) * EXP_M
                f = self.cell_floor(cx, cy, z)
                if f is None:
                    continue
                nvis = 0.0
                dps = 0.0
                for tx, ty, tz, tdps, tw in contacts:
                    eye = (tx, ty, tz + 8.0)
                    # a rival that sees only our head can still hit it
                    if (not self.los.fast(eye, (cx, cy, f + 4.5))) or (
                        hard and not self.los.fast(eye, (cx, cy, f + 8.8))
                    ):
                        nvis += tw
                        d = math.hypot(tx - cx, ty - cy)
                        dps += tw * (tdps if d < 200.0 else tdps * 0.25)
                exp[ej][ei] = W_EXP * dps + W_VIS * nvis

        zc = zone.get("center", (0.0, 0.0))
        zr = float(zone.get("radius", 0.0))
        inner = 0.7 * zr

        cost = [[W_INF] * SIZE for _ in range(SIZE)]
        floor = [[0.0] * SIZE for _ in range(SIZE)]
        for j in range(SIZE):
            for i in range(SIZE):
                cx = ox + (i - HALF) * CELL
                cy = oy + (j - HALF) * CELL
                f = self.cell_floor(cx, cy, z)
                if f is None or f > z + 3.0:
                    continue            # blocked, or a climb L2 does not do
                if zr > 1.0 and math.hypot(cx - zc[0], cy - zc[1]) > max(0.0, zr - 2.0):
                    continue            # never plan outside the live circle
                floor[j][i] = f
                c = CELL
                if hard:
                    d_dps, d_vis = self.exposure_at(cx, cy, f, contacts)
                    if d_vis >= 2.0 or d_dps >= 150.0:
                        continue        # no trading in the open at low HP
                clr = self.clearance(cx, cy)
                if clr < 4:
                    c += W_WALL * (4 - clr)
                c += self._bilinear(exp, (cx - x) / EXP_M + EXP_HALF,
                                    (cy - y) / EXP_M + EXP_HALF)
                if zr > 1.0:
                    c += 0.2 * max(0.0, math.hypot(cx - zc[0], cy - zc[1]) - inner)
                cost[j][i] = c

        if cost[sj][si] >= W_INF:
            best = None
            for j in range(SIZE):
                for i in range(SIZE):
                    if cost[j][i] < W_INF:
                        d = (i - si) ** 2 + (j - sj) ** 2
                        if best is None or d < best[0]:
                            best = (d, i, j)
            if best is None:
                return []
            si, sj = best[1], best[2]
        if cost[gj][gi] >= W_INF:
            best = None
            for j in range(SIZE):
                for i in range(SIZE):
                    if cost[j][i] < W_INF:
                        d = (i - gi) ** 2 + (j - gj) ** 2
                        if best is None or d < best[0]:
                            best = (d, i, j)
            if best is None:
                return []
            gi, gj = best[1], best[2]

        g = {sj * SIZE + si: 0.0}
        par = {sj * SIZE + si: -1}
        heap = [(0.0, 0.0, si, sj)]
        seen = set()
        goal_id = gj * SIZE + gi
        while heap:
            f, gc, i, j = heapq.heappop(heap)
            key = j * SIZE + i
            if key in seen:
                continue
            seen.add(key)
            if key == goal_id:
                break
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    if di == 0 and dj == 0:
                        continue
                    ni, nj = i + di, j + dj
                    if not (0 <= ni < SIZE and 0 <= nj < SIZE):
                        continue
                    if cost[nj][ni] >= W_INF:
                        continue
                    step = CELL * (1.41421356 if di and dj else 1.0)
                    dz = floor[nj][ni] - floor[j][i]
                    if dz > 2.75:
                        step += 100.0
                    elif dz > 1.2:
                        step += W_AIR + 0.5
                    nk = nj * SIZE + ni
                    ng = gc + cost[nj][ni] * (step / CELL)
                    if ng < g.get(nk, W_INF):
                        g[nk] = ng
                        par[nk] = key
                        h = math.hypot(gi - ni, gj - nj) * CELL
                        heapq.heappush(heap, (ng + h, ng, ni, nj))

        if goal_id not in par:
            return []
        cells = []
        cur = goal_id
        while cur >= 0:
            cells.append((cur % SIZE, cur // SIZE))
            cur = par[cur]
        cells.reverse()

        def world(c):
            return (ox + (c[0] - HALF) * CELL, oy + (c[1] - HALF) * CELL)

        def walk_line(a, b) -> bool:
            ax, ay = world(a)
            bx, by = world(b)
            d = math.hypot(bx - ax, by - ay)
            n = max(1, int(d))
            for q in range(1, n + 1):
                t = q / n
                px, py = ax + (bx - ax) * t, ay + (by - ay) * t
                f = self.cell_floor(px, py, z)
                if f is None or abs(f - z) > 1.2:
                    return False
            return True

        out = []
        idx = 1
        while idx < len(cells) and len(out) < 6:
            nxt = idx
            j = min(len(cells) - 1, idx + 8)      # up to 16 m of string pull
            while j > idx and not walk_line(cells[idx - 1], cells[j]):
                j -= 1
            nxt = max(idx, j)
            cx, cy = world(cells[nxt])
            f = floor[cells[nxt][1]][cells[nxt][0]]
            dz = f - z
            kind = 0
            if dz > 2.75:
                kind = 2
            elif dz > 1.2:
                kind = 1
            elif dz < -1.0:
                kind = 3
            out.append((cx, cy, f, kind))
            idx = nxt + 1
        if not out:
            out.append((ox, oy, floor[sj][si], 0))
        return out

    @staticmethod
    def _bilinear(grid, fx: float, fy: float) -> float:
        fx = max(0.0, min(EXP_N - 1.001, fx))
        fy = max(0.0, min(EXP_N - 1.001, fy))
        i, j = int(fx), int(fy)
        tx, ty = fx - i, fy - j
        a = grid[j][i] * (1 - tx) + grid[j][i + 1] * tx
        b = grid[j + 1][i] * (1 - tx) + grid[j + 1][i + 1] * tx
        return a * (1 - ty) + b * ty

    # --- emission ------------------------------------------------------
    def step(self, path: Sequence[Tuple[float, float, float, int]], me: dict,
             energy: float, walk: float) -> Tuple[Tuple[float, float], bool, bool, str]:
        """Return (move, jump, boost, label)."""
        if not path:
            return (0.0, 0.0), False, False, ""
        p = path[0]
        dx, dy = p[0] - me["pos"][0], p[1] - me["pos"][1]
        d = math.hypot(dx, dy)
        if d < 1.2:
            if len(path) > 1:
                p = path[1]
                dx, dy = p[0] - me["pos"][0], p[1] - me["pos"][1]
                d = math.hypot(dx, dy)
            else:
                # last waypoint reached: report arrival so the caller aims at
                # the real goal instead of turning around to the old cell
                return (0.0, 0.0), False, False, "arrived"
        if d < 1e-6:
            return (0.0, 0.0), False, False, "arrived"
        ux, uy = dx / d, dy / d
        dz = p[2] - me["pos"][2]
        grounded = bool(me.get("grounded", True))
        jump = False
        boost = False
        if dz > 1.2:
            if grounded:
                jump = True
            elif dz > 2.75 and energy > 12.0:
                boost = True
        return (ux, uy), jump, boost, "v%d" % p[3]

    def escape_dir(self, x: float, y: float, z: float) -> Tuple[float, float]:
        """Direction to the nearest standable cell when we are inside geometry
        (e.g. wedged under a low bridge deck)."""
        best = None
        for r in (2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 16.0, 20.0, 24.0, 30.0):
            for k in range(16):
                a = k * math.pi / 8.0
                ex, ey = x + math.cos(a) * r, y + math.sin(a) * r
                f = self.floor_at(ex, ey, z)
                if f is not None and f <= z + 2.75:
                    if best is None:
                        best = (math.cos(a), math.sin(a), r)
            if best is not None:
                return normalize2(best[0], best[1])
        return (0.0, 0.0)

    def find_cover(self, x: float, y: float, z: float, threat, radius: float = 15.0):
        """Nearest standable cell within `radius` that the threat cannot see.

        Scans a 2 m lattice; used only for laser telegraphs, so the cost is
        paid rarely and the result is cached by the caller.
        """
        eye = (threat[0], threat[1], threat[2] + 8.0)
        step = 3.0
        n = int(radius / step)
        best = None
        for di in range(-n, n + 1):
            for dj in range(-n, n + 1):
                cx, cy = x + di * step, y + dj * step
                d = math.hypot(di * step, dj * step)
                if d > radius or (best is not None and d >= best[0]):
                    continue
                f = self.floor_at(cx, cy, z)
                if f is None or f > z + 2.75:
                    continue
                if not self.los.sight(eye, (cx, cy, f + 4.5)):
                    continue
                if not self.los.sight(eye, (cx, cy, f + 8.8)):
                    continue
                best = (d, cx, cy)
        return (best[1], best[2]) if best else None

    # --- legality ------------------------------------------------------
    def legalize(self, mx: float, my: float, x: float, y: float, zone: dict,
                 z: Optional[float] = None) -> Tuple[float, float]:
        cx, cy = zone.get("center", (0.0, 0.0))
        r = float(zone.get("radius", 0.0))
        def ok(ux: float, uy: float, probe: float = 5.0) -> bool:
            ex, ey = x + ux * probe, y + uy * probe
            if not self.standable(ex, ey, z):
                return False
            if r > 1.0 and math.hypot(ex - cx, ey - cy) > r - 2.0:
                if math.hypot(ex - cx, ey - cy) > math.hypot(x - cx, y - cy):
                    return False
            return True

        base = math.atan2(my, mx)
        if ok(mx, my):
            return mx, my
        for probe in (5.0, 2.0):
            for deg in (30, -30, 60, -60, 90, -90, 120, -120, 180):
                a = base + math.radians(deg)
                ux, uy = math.cos(a), math.sin(a)
                if ok(ux, uy):
                    return ux, uy
        # no legal probe: stand still and let escape_dir() handle a blocked cell
        return 0.0, 0.0
