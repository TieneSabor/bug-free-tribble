"""Static world: terrain heightfield and polygon prisms."""
from __future__ import annotations

import json
import os
import sys
from array import array
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from mechbot.config import Config
from mechbot.geometry import (
    clip_segment_ring,
    point_in_ring,
    subtract_intervals,
)

BBox = Tuple[float, float, float, float]


class Prism:
    __slots__ = ("kind", "base", "top", "ring", "holes", "bbox")

    def __init__(self, d: Dict[str, object]):
        self.kind = str(d.get("kind", "building"))
        self.base = float(d.get("base", 0.0))
        self.top = float(d.get("top", 0.0))
        self.ring: List[float] = [float(v) for v in d.get("ring", [])]  # type: ignore[arg-type]
        self.holes: List[List[float]] = [
            [float(v) for v in h] for h in d.get("holes", [])  # type: ignore[union-attr]
        ]
        xs = self.ring[0::2]
        ys = self.ring[1::2]
        self.bbox = (min(xs), min(ys), max(xs), max(ys)) if xs else (0.0, 0.0, 0.0, 0.0)

    def contains_xy(self, x: float, y: float) -> bool:
        x0, y0, x1, y1 = self.bbox
        if x < x0 or x > x1 or y < y0 or y > y1:
            return False
        if not point_in_ring(x, y, self.ring):
            return False
        for hole in self.holes:
            if point_in_ring(x, y, hole):
                return False
        return True

    def contains_z(self, x: float, y: float, z: float) -> bool:
        return self.base <= z <= self.top and self.contains_xy(x, y)

    def segment_hits(self, a: Sequence[float], b: Sequence[float]) -> bool:
        dx, dy = b[0] - a[0], b[1] - a[1]
        intervals = clip_segment_ring(a[0], a[1], b[0], b[1], self.ring)
        if not intervals:
            return False
        for hole in self.holes:
            cuts = clip_segment_ring(a[0], a[1], b[0], b[1], hole)
            if cuts:
                intervals = subtract_intervals(intervals, cuts)
                if not intervals:
                    return False
        dz = b[2] - a[2]
        for t0, t1 in intervals:
            z0 = a[2] + dz * t0
            z1 = a[2] + dz * t1
            lo, hi = (z0, z1) if z0 <= z1 else (z1, z0)
            if hi >= self.base and lo <= self.top:
                return True
        return False

    def blocks_ground(self, x: float, y: float, ground_z: float, mech_height: float) -> bool:
        if not self.contains_xy(x, y):
            return False
        # A low top is a step; an overhead base clears the head.
        if self.top <= ground_z + 0.3:
            return False
        if self.base >= ground_z + mech_height:
            return False
        return True


class MapModel:
    """Loaded once at hello; immutable afterwards."""

    def __init__(self, map_info: Dict[str, object], cfg: Config):
        self.cfg = cfg
        files = list(map_info.get("files", []))
        base_dir = str(map_info.get("dir", "arena"))
        paths = {os.path.basename(str(f)): os.path.join(base_dir, str(f)) for f in files}
        world_path = paths.get("world.json", os.path.join(base_dir, "v2", "world.json"))
        terrain_path = paths.get("terrain.i16", os.path.join(base_dir, "v2", "terrain.i16"))

        with open(world_path, "r", encoding="utf-8") as f:
            world = json.load(f)
        self.world = world
        b = world.get("bounds", {})
        self.minx = float(b.get("minX", -513.0))
        self.maxx = float(b.get("maxX", 555.0))
        self.miny = float(b.get("minY", -334.0))
        self.maxy = float(b.get("maxY", 389.0))

        t = world.get("terrain", {})
        self.tminx = float(t.get("minX", -513.0))
        self.tminy = float(t.get("minY", -334.0))
        self.step = float(t.get("step", 1.0))
        self.nx = int(t.get("nx", 1070))
        self.ny = int(t.get("ny", 724))
        self.scale = float(t.get("scale", 0.01))

        with open(terrain_path, "rb") as f:
            raw = f.read()
        arr = array("h")
        arr.frombytes(raw[: self.nx * self.ny * 2])
        if sys.byteorder != "little":
            arr.byteswap()
        self.terrain = arr

        self.prisms = [Prism(p) for p in world.get("prisms", [])]
        self.cell = 32.0
        self._hash: Dict[Tuple[int, int], List[int]] = {}
        for i, p in enumerate(self.prisms):
            x0, y0, x1, y1 = p.bbox
            cx0 = int((x0 - self.minx) // self.cell)
            cx1 = int((x1 - self.minx) // self.cell)
            cy0 = int((y0 - self.miny) // self.cell)
            cy1 = int((y1 - self.miny) // self.cell)
            for cx in range(cx0, cx1 + 1):
                for cy in range(cy0, cy1 + 1):
                    self._hash.setdefault((cx, cy), []).append(i)

    # --- terrain ---------------------------------------------------------
    def height_at(self, x: float, y: float) -> float:
        u = (x - self.tminx) / self.step
        v = (y - self.tminy) / self.step
        u = 0.0 if u < 0.0 else (self.nx - 1.001 if u > self.nx - 1.001 else u)
        v = 0.0 if v < 0.0 else (self.ny - 1.001 if v > self.ny - 1.001 else v)
        i = int(u)
        j = int(v)
        i = min(max(i, 0), self.nx - 2)
        j = min(max(j, 0), self.ny - 2)
        fx = u - i
        fy = v - j
        n = self.nx
        h00 = self.terrain[j * n + i] * self.scale
        h10 = self.terrain[j * n + i + 1] * self.scale
        h01 = self.terrain[(j + 1) * n + i] * self.scale
        h11 = self.terrain[(j + 1) * n + i + 1] * self.scale
        return (
            h00 * (1 - fx) * (1 - fy)
            + h10 * fx * (1 - fy)
            + h01 * (1 - fx) * fy
            + h11 * fx * fy
        )

    def in_bounds(self, x: float, y: float, margin: float = 0.0) -> bool:
        return (
            self.minx + margin <= x <= self.maxx - margin
            and self.miny + margin <= y <= self.maxy - margin
        )

    # --- prism queries ---------------------------------------------------
    def _candidates(self, ax: float, ay: float, bx: float, by: float) -> Set[int]:
        x0, x1 = (ax, bx) if ax <= bx else (bx, ax)
        y0, y1 = (ay, by) if ay <= by else (by, ay)
        cx0 = int((x0 - self.minx) // self.cell)
        cx1 = int((x1 - self.minx) // self.cell)
        cy0 = int((y0 - self.miny) // self.cell)
        cy1 = int((y1 - self.miny) // self.cell)
        out: Set[int] = set()
        for cx in range(cx0, cx1 + 1):
            for cy in range(cy0, cy1 + 1):
                ids = self._hash.get((cx, cy))
                if ids:
                    out.update(ids)
        return out

    def ground_blocked(self, x: float, y: float) -> bool:
        if not self.in_bounds(x, y, 0.5):
            return True
        g = self.height_at(x, y)
        for i in self._candidates(x, y, x, y):
            if self.prisms[i].blocks_ground(x, y, g, self.cfg.height):
                return True
        return False

    def point_blocked(self, x: float, y: float, z: float) -> bool:
        for i in self._candidates(x, y, x, y):
            if self.prisms[i].contains_z(x, y, z):
                return True
        return False

    # --- lines of sight --------------------------------------------------
    def los(self, a: Sequence[float], b: Sequence[float]) -> bool:
        """True if the segment a->b is clear of terrain and prisms."""
        for idx in self._candidates(a[0], a[1], b[0], b[1]):
            if self.prisms[idx].segment_hits(a, b):
                return False
        # Terrain: sample at 1 m along the horizontal projection.
        dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        horiz = (dx * dx + dy * dy) ** 0.5
        n = max(1, int(horiz / 1.0))
        for k in range(1, n):
            t = k / n
            x = a[0] + dx * t
            y = a[1] + dy * t
            z = a[2] + dz * t
            if self.height_at(x, y) > z + 0.05:
                return False
        return True

    def shot_clear(self, a: Sequence[float], b: Sequence[float]) -> bool:
        # Trees do not block shots; all blocking geometry is already in los().
        return self.los(a, b)
