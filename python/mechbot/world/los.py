"""DDA line-of-sight over the baked 1 m occlusion layer.

Two predicates, deliberately different:
  shot(a, b)   terrain + prisms; trees do not stop bullets
  sight(a, b)  shot() plus canopy density beyond the 45 m near range

Both return True when the segment is **blocked**.
"""
from __future__ import annotations

from typing import Sequence

CANOPY_TAU = 3.9


class Los:
    __slots__ = ("g", "base", "top", "cov", "can", "nx", "ny", "minx", "miny")

    def __init__(self, st):
        self.g = st.occ["ground"]
        self.base = st.occ["base"]
        self.top = st.occ["top"]
        self.cov = st.occ["cov"]
        self.can = st.occ["canopy"]
        self.nx = st.nx
        self.ny = st.ny
        self.minx = st.min_x
        self.miny = st.min_y

    def shot(self, a: Sequence[float], b: Sequence[float]) -> bool:
        return self._ray(a, b, False, 1.0)

    def sight(self, a: Sequence[float], b: Sequence[float]) -> bool:
        # 0.5 m steps: a 1 m diagonal ray can step from (i,j) to (i+1,j+1)
        # without sampling (i+1,j) and miss a thin wall corner
        return self._ray(a, b, True, 0.5)

    def fast(self, a: Sequence[float], b: Sequence[float]) -> bool:
        return self._ray(a, b, False, 4.0)

    def clear(self, a: Sequence[float], b: Sequence[float]) -> bool:
        return not self.shot(a, b)

    # --- core ---------------------------------------------------------
    def _ray(self, a, b, sight: bool, step: float) -> bool:
        x0, y0, z0 = a
        x1, y1, z1 = b
        dx, dy, dz = x1 - x0, y1 - y0, z1 - z0
        horiz = (dx * dx + dy * dy) ** 0.5
        n = int(horiz / step)
        if n < 1:
            n = 1
        inv = 1.0 / n
        g, base, top = self.g, self.base, self.top
        cov, can = self.cov, self.can
        nx, ny, minx, miny = self.nx, self.ny, self.minx, self.miny
        acc = 0.0
        canopy_on = sight and horiz > 45.0
        for k in range(1, n):
            t = k * inv
            x = x0 + dx * t
            y = y0 + dy * t
            i = int(x - minx)
            j = int(y - miny)
            if i < 0 or j < 0 or i >= nx or j >= ny:
                return True
            idx = j * nx + i
            z = z0 + dz * t
            if z < g[idx] * 0.01 - 0.05:
                return True
            if cov[idx]:
                zb = base[idx] * 0.01
                if zb <= z <= top[idx] * 0.01:
                    return True
            if canopy_on and can[idx] and horiz * t > 45.0:
                acc += (can[idx] / 255.0) * (horiz * inv)
                if acc > CANOPY_TAU:
                    return True
        return False


class MapLos:
    """Fallback adapter so v1 zone-only behaviour can still run without the bake."""

    def __init__(self, mapmodel):
        self.map = mapmodel

    def shot(self, a, b) -> bool:
        return not self.map.los(a, b)

    def sight(self, a, b) -> bool:
        return self.shot(a, b)

    def fast(self, a, b) -> bool:
        return self.shot(a, b)

    def clear(self, a, b) -> bool:
        return not self.shot(a, b)
