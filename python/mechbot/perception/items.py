"""Remembered ground loot: weapon pickups, crates, cubes and supply drops.

`pickups`, `crates` and `cubes` are listed only while visible, so the bot has
to keep its own memory of them. `drops` are always known and are refreshed
every observation. An entry is deleted on hard evidence (we took it, someone
else took it while we could see the spot, it was destroyed) and ages out after
`LOOT_TTL_S`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Sequence, Tuple

from mechbot import tuning

PICKUP = "pickup"
CRATE = "crate"
CUBE = "cube"
DROP = "drop"

Vec3 = Tuple[float, float, float]


@dataclass
class Item:
    id: int
    kind: str
    pos: Vec3
    first_t: float
    last_seen_t: float
    detail: str = ""          # weapon kind for a pickup
    hp: float = 0.0           # crate health
    lands_in: float = 0.0     # supply drop
    radius: float = 0.0
    progress: float = 0.0
    holder: Any = None

    def age(self, now: float) -> float:
        return max(0.0, now - self.last_seen_t)

    def stale(self, now: float) -> bool:
        return self.age(now) > tuning.LOOT_STALE_S

    def dist2d(self, p: Sequence[float]) -> float:
        return ((self.pos[0] - p[0]) ** 2 + (self.pos[1] - p[1]) ** 2) ** 0.5

    def dz(self, p: Sequence[float]) -> float:
        return self.pos[2] - p[2]


class ItemMemory:
    """Per-match registry kept in sync from `obs`."""

    def __init__(self, cfg, visible=None):
        self.cfg = cfg
        self.visible = visible          # optional callable(pos) -> bool
        self.items: Dict[int, Item] = {}
        self.t = 0.0
        self.seen_this_tick = set()

    # --- update ------------------------------------------------------
    def update(self, obs: Dict[str, Any], now: float) -> None:
        self.t = now
        me = obs.get("self", {}) or {}
        my_pos = me.get("pos", (0.0, 0.0, 0.0))
        seen = set()

        for p in obs.get("pickups") or ():
            ident = self._ident(p)
            pos = p.get("pos")
            if ident is None or pos is None:
                continue
            it = self.items.get(ident)
            if it is None:
                it = Item(ident, PICKUP, _vec(pos), now, now,
                          detail=str(p.get("kind") or ""))
                self.items[ident] = it
            it.pos = _vec(pos)
            it.detail = str(p.get("kind") or it.detail)
            it.last_seen_t = now
            seen.add(ident)

        for c in obs.get("crates") or ():
            ident = self._ident(c)
            pos = c.get("pos")
            if ident is None or pos is None:
                continue
            it = self.items.get(ident)
            if it is None:
                it = Item(ident, CRATE, _vec(pos), now, now)
                self.items[ident] = it
            it.pos = _vec(pos)
            it.hp = _float(c.get("hp"), it.hp)
            it.last_seen_t = now
            seen.add(ident)

        for c in obs.get("cubes") or ():
            ident = self._ident(c)
            pos = c.get("pos")
            if ident is None or pos is None:
                continue
            it = self.items.get(ident)
            if it is None:
                it = Item(ident, CUBE, _vec(pos), now, now)
                self.items[ident] = it
            it.pos = _vec(pos)
            it.last_seen_t = now
            seen.add(ident)

        for d in obs.get("drops") or ():
            ident = self._ident(d)
            pos = d.get("pos")
            if ident is None or pos is None:
                continue
            it = self.items.get(ident)
            if it is None:
                it = Item(ident, DROP, _vec(pos), now, now)
                self.items[ident] = it
            it.pos = _vec(pos)
            it.lands_in = _float(d.get("lands_in"), 0.0)
            it.radius = _float(d.get("radius"), 8.0)
            it.progress = _float(d.get("progress"), 0.0)
            it.holder = d.get("holder")
            it.last_seen_t = now
            seen.add(ident)

        self._events(obs)
        self._forget(seen, obs.get("drops") or (), my_pos, now, me)
        self.seen_this_tick = seen

    def _events(self, obs: Dict[str, Any]) -> None:
        for ev in obs.get("events") or ():
            typ = ev.get("type")
            if typ == "took":
                self.items.pop(_int(ev.get("id")), None)
            elif typ == "take_failed" and ev.get("reason") == "gone":
                self.items.pop(_int(ev.get("id")), None)
            elif typ == "kill":
                pass

    def _forget(self, seen, drops, my_pos, now: float, me: Dict[str, Any]) -> None:
        near = float(self.cfg.near_range)
        # drops are always known: absent from obs means someone captured it
        drop_ids = {_int(d.get("id")) for d in drops}
        for ident, it in list(self.items.items()):
            if it.kind == DROP:
                if ident not in drop_ids:
                    self.items.pop(ident, None)
                continue
            if ident in seen:
                continue
            if it.age(now) > tuning.LOOT_TTL_S:
                self.items.pop(ident, None)
                continue
            # we are close enough that it must be in near vision if it still
            # existed: it was taken or destroyed. Only trust that when we can
            # actually see the spot (buildings block proximity sensors).
            if (it.dist2d(my_pos) <= near and abs(it.dz(my_pos)) <= 10.0
                    and (self.visible is None or self.visible(it.pos))):
                self.items.pop(ident, None)

    @staticmethod
    def _ident(obj: Dict[str, Any]):
        try:
            v = int(obj.get("id", -1))
        except (TypeError, ValueError):
            return None
        return v if v >= 0 else None

    # --- queries -----------------------------------------------------
    def of_kind(self, kind: str):
        return [it for it in self.items.values() if it.kind == kind]

    def get(self, ident):
        return self.items.get(_int(ident))

    def forget(self, ident) -> None:
        self.items.pop(_int(ident), None)


def _vec(p) -> Vec3:
    return (float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0)


def _float(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return -1
