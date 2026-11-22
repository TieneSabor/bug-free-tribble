"""Arm 1 loot choice: reachability x arrival race x local opposition.

The score is deliberately boring and inspectable:

    U = V * p_race * exp(-S/S0) - time_price*eta - damage_price*E[damage]

with hard vetoes for the zone, the trip radius and a hostile DPS we cannot
beat. Everything monotonically "more is better", so a trace can be read by
hand. Arm 2 replaces the observed-only `S` with the strength field.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from mechbot import tuning
from mechbot import power as st
from mechbot.geometry import angle_diff, bearing, clamp
from mechbot.perception.items import CRATE, CUBE, DROP, PICKUP, Item


@dataclass
class Pick:
    id: int
    kind: str
    pos: Tuple[float, float, float]
    score: float
    eta: float
    value: float
    p_race: float
    threat: float
    damage: float
    reason: str
    detail: str = ""


class LootChooser:
    def __init__(self, cfg):
        self.cfg = cfg
        self.target_id: Optional[int] = None
        self.target_t = -1e9
        self.blacklist: Dict[int, float] = {}
        self.sent: Dict[int, float] = {}
        self.t = 0.0
        self.reason = ""
        self._best_d = None
        self._best_t = -1e9

    # --- public -------------------------------------------------------
    def select(self, bf, field, now: float) -> Optional[Pick]:
        self.t = now
        items = getattr(bf, "items", None)
        if items is None:
            self._latch(None, now)
            return None
        me = bf.me
        my_pos = me.get("pos", (0.0, 0.0, 0.0))
        hp = float(me.get("hp", self.cfg.max_hp))
        mhp = max(1.0, float(me.get("max_hp", self.cfg.max_hp)))
        hpf = hp / mhp
        cubes = int(me.get("cubes") or 0)
        held = set(st.held_kinds(me))
        slots = me.get("weapons") or []
        slot1_empty = len(slots) < 2 or slots[1] is None
        can_swap = self._mortar_in_slot1(me)
        p_us = st.our_power(self.cfg, me, 80.0) or 1.0
        zone = bf.zone
        zc = zone.get("center", (0.0, 0.0))
        zr = float(zone.get("radius", 0.0))

        best: Optional[Pick] = None
        for it in items.items.values():
            if self.blacklist.get(it.id, -1e9) > now:
                continue
            d = it.dist2d(my_pos)
            value, reason = self._value(it, held, slot1_empty, can_swap, cubes, hpf)
            if value is None:
                continue
            if it.kind == DROP and self._crowded(bf, it.pos, tuning.LOOT_DROP_ALONE_M):
                continue          # capture freezes with a second mech in the ring
            first_secondary = it.kind == PICKUP and slot1_empty
            max_d = (tuning.LOOT_RADIUS_FIRST_M if first_secondary
                     else tuning.LOOT_RADIUS_M)
            if it.kind == DROP:
                max_d = max(max_d, 200.0)
            if d > max_d:
                continue
            if abs(it.dz(my_pos)) > 3.5:
                continue          # arm 1: ground loot only
            if math.hypot(it.pos[0] - zc[0], it.pos[1] - zc[1]) > max(1.0, zr):
                continue          # already outside the current circle
            walk = max(1.0, float((me.get("stats") or {}).get(
                "walk_speed", self.cfg.walk_speed)))
            eta = d * 1.25 / walk + 0.35
            if it.stale(now):
                eta += 6.0
            if not self._zone_ok(field, zone, it.pos, now, eta):
                continue
            p_race, race_note = self._race(bf, it.pos, eta, now)
            if p_race < tuning.LOOT_RACE_FLOOR:
                continue
            if it.kind == DROP:
                eta = max(eta, float(it.lands_in))
            threat = self._threat(bf, it.pos)
            if threat > tuning.LOOT_ITEM_VETO * p_us:
                continue
            damage = threat * eta * tuning.LOOT_EXPOSURE_FRAC
            if damage > tuning.LOOT_DAMAGE_FRAC * hp:
                continue
            score = (value * p_race * math.exp(-threat / tuning.LOOT_THREAT_SCALE)
                     - tuning.LOOT_TIME_PRICE * eta
                     - tuning.LOOT_DAMAGE_PRICE * damage)
            if it.id == self.target_id:
                score *= tuning.LOOT_LATCH_BONUS
            if best is None or score > best.score:
                best = Pick(it.id, it.kind, it.pos, score, eta, value, p_race,
                            threat, damage,
                            "%s%s%s" % (reason, race_note,
                                        " stale" if it.stale(now) else ""),
                            detail=it.detail)
        drone = self._drone_pick(bf, my_pos, hpf, held, zone, field, p_us, now)
        if drone is not None and (best is None or drone.score > best.score):
            best = drone
        if best is None or best.score < tuning.LOOT_MIN_SCORE:
            self._latch(None, now)
            self.reason = "none" if best is None else "low %.2f" % best.score
            return None
        self.reason = "%s %.2f" % (best.reason, best.score)
        self._latch(best.id, now)
        self._watch(best, my_pos, now)
        return best

    def take_id(self, bf, pick: Optional[Pick], now: float = 0.0):
        """(pickup id, drop slot) to claim this decision, or None."""
        if pick is not None and pick.kind == PICKUP and not self._quarantined(pick.id, now):
            me = bf.me
            my_pos = me.get("pos", (0.0, 0.0, 0.0))
            reach = float(self.cfg.pickup_radius)
            d = math.hypot(pick.pos[0] - my_pos[0], pick.pos[1] - my_pos[1])
            if d <= reach - 0.4 and abs(pick.pos[2] - my_pos[2]) <= 3.5:
                self.sent[pick.id] = now
                return pick.id, self._drop_slot(me, pick.detail)
        return self.grab_adjacent(bf, now)

    # --- drone candidates ---------------------------------------------
    def _drone_pick(self, bf, my_pos, hpf: float, held, zone, field,
                    p_us: float, now: float) -> Optional[Pick]:
        """A drone is 2 cubes for 350 HP of damage: farm it when healthy."""
        if hpf < tuning.LOOT_DRONE_HP:
            return None
        best = None
        zc = zone.get("center", (0.0, 0.0))
        zr = float(zone.get("radius", 0.0))
        walk = max(1.0, float((bf.me.get("stats") or {}).get(
            "walk_speed", self.cfg.walk_speed)))
        for t in bf.tracks.values():
            if t.kind != "npc" or t.dead or t.pos is None:
                continue
            d = math.hypot(t.pos[0] - my_pos[0], t.pos[1] - my_pos[1])
            if d > tuning.LOOT_DRONE_M:
                continue
            if math.hypot(t.pos[0] - zc[0], t.pos[1] - zc[1]) > max(1.0, zr):
                continue
            eta = d * 1.25 / walk + 0.35
            if not self._zone_ok(field, zone, t.pos, now, eta):
                continue
            threat = self._threat(bf, t.pos)
            if threat > tuning.LOOT_ITEM_VETO * p_us:
                continue
            damage = threat * eta * tuning.LOOT_EXPOSURE_FRAC
            if damage > tuning.LOOT_DAMAGE_FRAC * float(bf.me.get("hp", self.cfg.max_hp)):
                continue
            score = (tuning.LOOT_DRONE_VALUE
                     * math.exp(-threat / tuning.LOOT_THREAT_SCALE)
                     - tuning.LOOT_TIME_PRICE * eta
                     - tuning.LOOT_DAMAGE_PRICE * damage)
            if score < tuning.LOOT_MIN_SCORE:
                continue
            cand = Pick(t.id, "drone", t.pos, score, eta,
                        tuning.LOOT_DRONE_VALUE, 1.0, threat, damage,
                        "drone %d" % t.id)
            if best is None or cand.score > best.score:
                best = cand
        return best

    def grab_adjacent(self, bf, now: float = 0.0):
        """Free loot under our feet, even while hurt or rotating.

        The trip price does not apply at zero distance, so this bypasses the
        LOOT mode gate: if we walk over a weapon we want, we take it. A mortar
        in slot 1 is swapped out for a laser or a lightning, because arm 1
        otherwise blocks the slot for the rest of the match.
        """
        items = getattr(bf, "items", None)
        if items is None or not items.items:
            return None
        me = bf.me
        my_pos = me.get("pos", (0.0, 0.0, 0.0))
        held = set(st.held_kinds(me))
        slots = me.get("weapons") or []
        slot1_empty = len(slots) < 2 or slots[1] is None
        can_swap = self._mortar_in_slot1(me)
        reach = float(self.cfg.pickup_radius)
        best, best_v = None, 0.0
        for it in items.items.values():
            if it.kind != PICKUP or not it.detail or it.detail in held:
                continue
            v = tuning.LOOT_KIND_VALUE.get(it.detail, 0.0)
            if v <= 0.0 or self._quarantined(it.id, now):
                continue
            if not slot1_empty and not (can_swap and it.detail in ("laser", "lightning")):
                continue
            if it.dist2d(my_pos) > reach - 0.4 or abs(it.dz(my_pos)) > 3.5:
                continue
            if v > best_v:
                best, best_v = it, v
        if best is None:
            return None
        self.sent[best.id] = now
        return best.id, self._drop_slot(me, best.detail)

    # --- take plumbing ------------------------------------------------
    def _quarantined(self, ident: int, now: float) -> bool:
        return now - self.sent.get(ident, -1e9) < tuning.TAKE_QUARANTINE_S

    def _mortar_in_slot1(self, me) -> bool:
        if not tuning.LOOT_SWAP_ENABLE:
            return False
        slots = me.get("weapons") or []
        if len(slots) < 2 or slots[1] is None:
            return False
        w = slots[1]
        kind = str(w.get("kind") if isinstance(w, dict) else w)
        return kind == "mortar"

    def _drop_slot(self, me, kind: str) -> Optional[int]:
        if kind not in ("laser", "lightning"):
            return None
        return 1 if self._mortar_in_slot1(me) else None

    # --- internals ----------------------------------------------------
    def _value(self, it: Item, held, slot1_empty: bool, can_swap: bool,
               cubes: int, hpf: float) -> Tuple[Optional[float], str]:
        if it.kind == PICKUP:
            kind = it.detail
            if not kind or kind in held:
                return None, ""
            kv = tuning.LOOT_KIND_VALUE.get(kind, 0.0)
            if kv <= 0.0:
                return None, ""
            if kind == "mortar" and self.t < tuning.LOOT_MORTAR_AFTER_S:
                return None, ""
            if slot1_empty:
                return tuning.LOOT_FIRST_SECONDARY * kv, kind
            if can_swap and kind in ("laser", "lightning"):
                return tuning.LOOT_SWAP_VALUE * kv, kind + " swap"
            return None, ""
        if it.kind == CRATE:
            return (tuning.LOOT_CRATE_UNARMED if slot1_empty
                    else tuning.LOOT_CRATE), "crate"
        if it.kind == CUBE:
            return self._cube_value(cubes, hpf), "cube"
        if it.kind == DROP:
            if float(it.lands_in) > tuning.LOOT_DROP_MAX_WAIT:
                return None, ""
            return tuning.LOOT_DROP * (1.0 + (1.0 - hpf)), "drop"
        return None, ""

    def _cube_value(self, cubes: int, hpf: float) -> float:
        cap = int(self.cfg.stat_cap)
        th = [int(x) for x in (self.cfg.cubes.get("upgrade_thresholds") or ())]
        nxt = next((t for t in th if t > cubes), None)
        near = nxt is not None and (nxt - cubes) <= 1
        if cubes < cap:
            v = tuning.LOOT_CUBE_STAT * (cap - cubes) / float(cap)
        else:
            v = 0.05
        v += tuning.LOOT_CUBE_HEAL * (1.0 - hpf)
        if near:
            v += tuning.LOOT_CUBE_UPGRADE
        return v

    def _zone_ok(self, field, zone, pos, now: float, eta: float) -> bool:
        if field is None or not getattr(field, "eta", None):
            return True
        try:
            dl = field.deadline(zone, pos, now)
        except Exception:  # noqa: BLE001 - field is optional in tests
            return True
        return now + eta + tuning.LOOT_ZONE_MARGIN_S <= dl - tuning.LOOT_ZONE_MARGIN_S

    def _crowded(self, bf, pos, radius: float) -> bool:
        for t in bf.tracks.values():
            if t.kind != "mech" or t.dead or t.pos is None:
                continue
            if math.hypot(t.pos[0] - pos[0], t.pos[1] - pos[1]) <= radius:
                return True
        return False

    def _race(self, bf, pos, eta: float, now: float) -> Tuple[float, str]:
        me_pos = bf.me.get("pos", (0.0, 0.0, 0.0))
        mine = math.hypot(pos[0] - me_pos[0], pos[1] - me_pos[1])
        best = None
        for t in bf.tracks.values():
            if t.kind != "mech" or t.dead or t.pos is None:
                continue
            d_item = math.hypot(pos[0] - t.pos[0], pos[1] - t.pos[1])
            if d_item > tuning.LOOT_RACE_RADIUS_M:
                continue
            if d_item <= 4.0:
                return 0.02, " occupied"
            walk = 11.7
            e = d_item / walk
            if t.vel is not None:
                vx, vy = float(t.vel[0]), float(t.vel[1])
                n = math.hypot(vx, vy)
                if n > 1.0:
                    ux, uy = vx / n, vy / n
                    dx, dy = pos[0] - t.pos[0], pos[1] - t.pos[1]
                    dn = math.hypot(dx, dy) or 1.0
                    cosang = (ux * dx + uy * dy) / dn
                    if cosang < -0.5:
                        e += tuning.LOOT_RACE_TURN_S
                    elif cosang < 0.0:
                        e += 0.5 * tuning.LOOT_RACE_TURN_S
            if best is None or e < best:
                best = e
        if best is None:
            return 1.0, ""
        if math.hypot(pos[0] - me_pos[0], pos[1] - me_pos[1]) < 0.01:
            return 0.5, ""
        delta = best - eta
        p = 1.0 / (1.0 + math.exp(-delta / tuning.LOOT_RACE_SIGMA_S))
        return clamp(p, 0.0, 1.0), (" race %.2f" % p)

    def _threat(self, bf, pos) -> float:
        total = 0.0
        for t in bf.tracks.values():
            if t.kind != "mech" or t.dead or t.pos is None:
                continue
            d = math.hypot(pos[0] - t.pos[0], pos[1] - t.pos[1])
            if d > tuning.LOOT_THREAT_M:
                continue
            if not self._can_see(t, pos, d):
                continue
            hp_frac = t.hp_frac if t.hp_frac is not None else 0.75
            total += st.power(self.cfg, hp_frac, int(t.cubes or 0),
                              t.weapons or ("gun",), max(10.0, d))
        return total

    def _can_see(self, t, pos, d: float) -> bool:
        if d <= float(self.cfg.near_range):
            return True
        if d > float(self.cfg.vision_range):
            return False
        if t.aim is None:
            return True
        brg = bearing(t.pos[0], t.pos[1], pos[0], pos[1])
        half = math.radians(float(self.cfg.fov_deg)) * 0.5
        return abs(angle_diff(float(t.aim[0]), brg)) <= half

    def _latch(self, ident: Optional[int], now: float) -> None:
        if ident != self.target_id:
            self.target_id = ident
            self.target_t = now
            self._best_d = None
            self._best_t = now

    def _watch(self, pick: Pick, my_pos, now: float) -> None:
        d = math.hypot(pick.pos[0] - my_pos[0], pick.pos[1] - my_pos[1])
        if self._best_d is None or d < self._best_d - 2.0:
            self._best_d = d
            self._best_t = now
        elif now - self._best_t > tuning.LOOT_STALL_S:
            self.blacklist[pick.id] = now + tuning.LOOT_BLACKLIST_S
            self._best_d = d
            self._best_t = now
