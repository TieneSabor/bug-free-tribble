"""Semantic roadmap: snap, route, corridor, cover."""
from __future__ import annotations

import heapq
import math
from typing import Dict, List, Optional, Sequence, Tuple

NODE_BUCKET = 16.0


class Corridor:
    __slots__ = ("nodes", "kinds", "goal")

    def __init__(self, nodes, kinds, goal):
        self.nodes = nodes
        self.kinds = kinds
        self.goal = goal

    def __repr__(self):
        return "<Corridor %d nodes goal=%s>" % (len(self.nodes), self.goal)


class Roadmap:
    def __init__(self, st, los):
        self.st = st
        self.los = los
        n = st.nodes
        self.n = int(st.meta["nodes"])
        self.main = int(st.meta["main_comp"])
        self.x = n["x"]
        self.y = n["y"]
        self.z = n["z"]
        self.layer = n["layer"]
        self.clear = n["clear"]
        self.comp = n["comp"]
        self.hn = n["hidden_near"]
        self.hf = n["hidden_far"]
        self.conceal = n["conceal"]
        self.escapes = n["escapes"]
        self.open_dir = n["open_dir"]
        self.hold = n["hold"]
        e = st.edges
        self.off = e["off"]
        self.dst = e["dst"]
        self.length = e["len"]
        self.kind = e["kind"]
        self.alt = st.alt
        self.nl = len(self.alt)
        self.buckets: Dict[Tuple[int, int], List[int]] = {}
        for k in range(self.n):
            self.buckets.setdefault(self._key(self.x[k], self.y[k]), []).append(k)
        self.main_nodes = [k for k in range(self.n) if self.comp[k] == self.main] or list(
            range(self.n)
        )

    # --- helpers ------------------------------------------------------
    def _key(self, x: float, y: float) -> Tuple[int, int]:
        return (int(x // NODE_BUCKET), int(y // NODE_BUCKET))

    def snap(self, x: float, y: float) -> int:
        best, bd = -1, 1e18
        best_main, bd_main = -1, 1e18
        for k in self.near_nodes(x, y, 24.0):
            d = (self.x[k] - x) ** 2 + (self.y[k] - y) ** 2
            if d < bd:
                best, bd = k, d
            if self.comp[k] == self.main and d < bd_main:
                best_main, bd_main = k, d
        if best_main >= 0:
            return best_main
        if best >= 0:
            return best
        for k in self.main_nodes:
            d = (self.x[k] - x) ** 2 + (self.y[k] - y) ** 2
            if d < bd:
                best, bd = k, d
        return best

    def near_nodes(self, x: float, y: float, radius: float) -> List[int]:
        r = int(math.ceil(radius / NODE_BUCKET))
        kx, ky = int(x // NODE_BUCKET), int(y // NODE_BUCKET)
        r2 = radius * radius
        out = []
        for bx in range(kx - r, kx + r + 1):
            for by in range(ky - r, ky + r + 1):
                for k in self.buckets.get((bx, by), ()):
                    if (self.x[k] - x) ** 2 + (self.y[k] - y) ** 2 <= r2:
                        out.append(k)
        return out

    def _h(self, a: int, b: int) -> float:
        h = 0.0
        for r in range(self.nl):
            v = abs(self.alt[r][a] - self.alt[r][b])
            if v > h:
                h = v
        return h * 0.1

    # --- routing ------------------------------------------------------
    def route(self, a: int, b: int, cap: float = 4000.0) -> List[int]:
        if a < 0 or b < 0:
            return []
        if a == b:
            return [a]
        g = {a: 0.0}
        parent = {a: -1}
        heap = [(self._h(a, b), 0.0, a)]
        seen = set()
        off, dst, ln = self.off, self.dst, self.length
        while heap:
            f, gc, u = heapq.heappop(heap)
            if u in seen:
                continue
            seen.add(u)
            if u == b:
                path = [u]
                while parent[path[-1]] >= 0:
                    path.append(parent[path[-1]])
                path.reverse()
                return path
            if gc > cap:
                continue
            for e in range(off[u], off[u + 1]):
                v = dst[e]
                ng = gc + ln[e]
                if ng < g.get(v, 1e18):
                    g[v] = ng
                    parent[v] = u
                    heapq.heappush(heap, (ng + self._h(v, b), ng, v))
        return []

    def corridor(self, x: float, y: float, gx: float, gy: float) -> Corridor:
        a = self.snap(x, y)
        b = self.snap(gx, gy)
        path = self.route(a, b)
        if not path:
            return Corridor([], [], (gx, gy))
        kinds = []
        for i in range(len(path) - 1):
            kinds.append(self._edge_kind(path[i], path[i + 1]))
        return Corridor(path, kinds, (gx, gy))

    def _edge_kind(self, a: int, b: int) -> int:
        for e in range(self.off[a], self.off[a + 1]):
            if self.dst[e] == b:
                return int(self.kind[e])
        return 0

    # --- cover --------------------------------------------------------
    def cover(self, me_x, me_y, me_z, threats, radius: float = 60.0) -> List[int]:
        if not threats:
            return []
        secs = []
        for t in threats:
            brg = math.atan2(t[1] - me_y, t[0] - me_x) if False else None
            secs.append(t)
        cands = self.near_nodes(me_x, me_y, radius)
        out = []
        for k in cands:
            if self.comp[k] != self.main:
                continue
            ok = True
            sector = []
            for tx, ty, _tz in threats:
                brg = math.atan2(ty - self.y[k], tx - self.x[k])
                d = int(((brg + math.pi) / (math.pi / 4.0))) % 8
                bit = 1 << d
                dist = math.hypot(tx - self.x[k], ty - self.y[k])
                mask = self.hn[k] if dist < 90.0 else self.hf[k]
                if not (mask & bit):
                    ok = False
                    break
                sector.append((tx, ty))
            if not ok:
                continue
            out.append((self.conceal[k], -math.hypot(self.x[k] - me_x, self.y[k] - me_y), k))
        out.sort(reverse=True)
        verified = []
        for _conceal, _d, k in out[:8]:
            body = (self.x[k], self.y[k], self.z[k] + 4.5)
            top = (self.x[k], self.y[k], self.z[k] + 8.8)
            hidden = True
            for tx, ty, tz in threats:
                eye = (tx, ty, tz + 8.0)
                if not self.los.sight(eye, body) or not self.los.sight(eye, top):
                    hidden = False
                    break
            if hidden:
                verified.append(k)
        return verified

    def node(self, k: int):
        return (self.x[k], self.y[k], self.z[k])
