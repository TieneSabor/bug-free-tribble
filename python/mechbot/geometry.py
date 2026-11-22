"""Pure geometry helpers. No game or map imports."""
from __future__ import annotations

import math
from typing import Iterable, List, Sequence, Tuple


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def wrap_angle(a: float) -> float:
    """Wrap to [-pi, pi]."""
    while a > math.pi:
        a -= 2.0 * math.pi
    while a < -math.pi:
        a += 2.0 * math.pi
    return a


def angle_diff(a: float, b: float) -> float:
    return wrap_angle(a - b)


def bearing(x0: float, y0: float, x1: float, y1: float) -> float:
    return math.atan2(y1 - y0, x1 - x0)


def dist2(a: Sequence[float], b: Sequence[float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def dist3(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def dot2(ax: float, ay: float, bx: float, by: float) -> float:
    return ax * bx + ay * by


def length2(x: float, y: float) -> float:
    return math.hypot(x, y)


def normalize2(x: float, y: float) -> Tuple[float, float]:
    n = math.hypot(x, y)
    if n < 1e-9:
        return 0.0, 0.0
    return x / n, y / n


def perp(x: float, y: float) -> Tuple[float, float]:
    return -y, x


def lerp2(a: Sequence[float], b: Sequence[float], t: float) -> Tuple[float, float]:
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t


def point_segment_distance(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> Tuple[float, float]:
    """Return (distance from p to segment ab, parameter t in [0,1])."""
    dx, dy = bx - ax, by - ay
    den = dx * dx + dy * dy
    if den < 1e-12:
        return math.hypot(px - ax, py - ay), 0.0
    t = ((px - ax) * dx + (py - ay) * dy) / den
    t = clamp(t, 0.0, 1.0)
    qx, qy = ax + dx * t, ay + dy * t
    return math.hypot(px - qx, py - qy), t


def point_in_ring(x: float, y: float, ring: Sequence[float]) -> bool:
    """Even-odd point in a flat [x0,y0,x1,y1,...] polygon."""
    n = len(ring) // 2
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = ring[2 * i], ring[2 * i + 1]
        xj, yj = ring[2 * j], ring[2 * j + 1]
        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi + 1e-30) + xi
        ):
            inside = not inside
        j = i
    return inside


def clip_segment_ring(
    ax: float, ay: float, bx: float, by: float, ring: Sequence[float]
) -> List[Tuple[float, float]]:
    """Return t-intervals [t0,t1] of segment a->b inside a ring."""
    if len(ring) < 6:
        return []
    ts = [0.0, 1.0]
    n = len(ring) // 2
    dx, dy = bx - ax, by - ay
    for i in range(n):
        j = (i + 1) % n
        ex = ring[2 * j] - ring[2 * i]
        ey = ring[2 * j + 1] - ring[2 * i + 1]
        den = dx * ey - dy * ex
        if abs(den) < 1e-12:
            continue
        qx = ring[2 * i] - ax
        qy = ring[2 * i + 1] - ay
        t = (qx * ey - qy * ex) / den
        if 0.0 <= t <= 1.0:
            ts.append(t)
    ts = sorted(set(ts))
    out: List[Tuple[float, float]] = []
    for k in range(len(ts) - 1):
        t0, t1 = ts[k], ts[k + 1]
        if t1 - t0 < 1e-9:
            continue
        m = 0.5 * (t0 + t1)
        if point_in_ring(ax + dx * m, ay + dy * m, ring):
            if out and abs(out[-1][1] - t0) < 1e-9:
                out[-1] = (out[-1][0], t1)
            else:
                out.append((t0, t1))
    return out


def subtract_intervals(
    base: Iterable[Tuple[float, float]], cuts: Iterable[Tuple[float, float]]
) -> List[Tuple[float, float]]:
    """Subtract cut intervals from base intervals."""
    cur = list(base)
    for c0, c1 in cuts:
        nxt: List[Tuple[float, float]] = []
        for b0, b1 in cur:
            if c1 <= b0 or c0 >= b1:
                nxt.append((b0, b1))
                continue
            if c0 > b0:
                nxt.append((b0, c0))
            if c1 < b1:
                nxt.append((c1, b1))
        cur = nxt
        if not cur:
            break
    return cur
