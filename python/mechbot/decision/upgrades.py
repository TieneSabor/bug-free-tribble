"""Upgrade offers: value the three choices instead of taking choice 0.

Every effect is converted to HP-equivalent using `tuning.UPG_*`, then the best
choice wins. Two details matter more than the weights:

- weapon cooldowns are quantised to the 0.1 s decision grid before they are
  valued: the gun can only fire on the first tick of a decision, so
  `cooldown 0.24` really fires every 0.3 s. One `gun_rate` stack (0.209 s)
  buys nothing at all; two stacks (0.181 s) buy +50 %;
- armor has increasing returns (effective HP is 1/(1-armor)), so the third
  stack is worth more than the first.

Offers queue and expire after 5 s with choice 0 applied, so this always
answers as soon as an offer is present.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from mechbot import tuning


def decision_interval(cd: float) -> float:
    """Smallest decision-grid interval that can honour this cooldown."""
    return max(0.1, math.ceil(max(0.0, cd) / 0.1 - 1e-9) * 0.1)


def shots_per_s(cd: float) -> float:
    return 1.0 / decision_interval(cd)


class UpgradePolicy:
    def __init__(self, cfg):
        self.cfg = cfg
        defs = cfg.upgrades
        if isinstance(defs, dict):
            defs = list(defs.values())
        self.defs: Dict[str, Dict[str, Any]] = {}
        for u in defs or ():
            try:
                self.defs[str(u.get("id"))] = u
            except AttributeError:
                continue
        self.last = ""
        self._warned = False

    # --- api ----------------------------------------------------------
    def choose(self, offer: Optional[Dict[str, Any]], me: Dict[str, Any]
               ) -> Optional[int]:
        if not offer or not tuning.UPGRADE_ENABLE:
            return None
        choices = offer.get("choices") or ()
        if not choices:
            return None
        held = set()
        for w in me.get("weapons") or ():
            if w:
                held.add(str(w.get("kind") if isinstance(w, dict) else w))
        best, best_score = 0, -1e18
        notes = []
        for i, ch in enumerate(choices):
            cid = str((ch or {}).get("id") or "")
            up = self.defs.get(cid)
            if up is None:
                score = tuning.UPG_UNKNOWN_HP
            else:
                req = up.get("requires")
                if req and str(req) not in held:
                    score = 0.0
                else:
                    score = self.score(up, me)
            notes.append("%s=%.0f" % (cid or "?", score))
            if score > best_score:
                best, best_score = i, score
        self.last = " ".join(notes)
        return best

    # --- scoring ------------------------------------------------------
    def score(self, up: Dict[str, Any], me: Dict[str, Any]) -> float:
        total = 0.0
        for eff in up.get("effects") or ():
            try:
                total += self._effect(str(eff.get("path") or ""), eff, me)
            except (TypeError, ValueError):
                total += tuning.UPG_UNKNOWN_HP
        return total

    def _effect(self, path: str, eff: Dict[str, Any], me: Dict[str, Any]) -> float:
        mul = float(eff.get("mul", 1.0))
        add = float(eff.get("add", 0.0))
        stats = self.cfg.stats_for(me)
        mhp = max(1.0, float(me.get("max_hp", self.cfg.max_hp)))

        if path == "mech.hp":
            return (mul - 1.0) * mhp + add
        if path == "mech.armor":
            old = max(0.0, min(0.85, float(stats.get("armor", 0.0))))
            new = max(0.0, min(0.85, old + add))
            return (1.0 / (1.0 - new) - 1.0 / (1.0 - old)) * tuning.UPG_ARMOR_HP
        if path == "mech.regen_per_s":
            regen = float(stats.get("regen_per_s", self.cfg.regen_per_s))
            return (mul - 1.0) * regen * tuning.UPG_REGEN_SECONDS
        if path == "mech.regen_delay":
            regen = float(stats.get("regen_per_s", self.cfg.regen_per_s))
            return -add * regen
        if path in ("mech.walk_speed", "mech.boost_speed"):
            return (mul - 1.0) * tuning.UPG_SPEED_HP
        if path in ("mech.turn_rate", "mech.pitch_rate"):
            return (mul - 1.0) * tuning.UPG_TURN_HP
        if path == "mech.energy":
            return add * (tuning.UPG_ENERGY_HP / 30.0)
        if path == "mech.energy_regen":
            return (mul - 1.0) * tuning.UPG_EREGEN_HP
        if path in ("mech.boost_drain", "mech.jet_drain"):
            return (1.0 - mul) * tuning.UPG_DRAIN_HP
        if path in ("mech.near_range_bonus", "mech.vision_bonus", "mech.hearing"):
            return tuning.UPG_SENSE_HP
        if path.startswith("weapons."):
            return self._weapon(path, mul, add, me)
        return tuning.UPG_UNKNOWN_HP

    def _weapon(self, path: str, mul: float, add: float, me: Dict[str, Any]) -> float:
        parts = path.split(".")
        kind = parts[1] if len(parts) > 1 else ""
        stat = parts[2] if len(parts) > 2 else ""
        held = {str(w.get("kind") if isinstance(w, dict) else w)
                for w in (me.get("weapons") or ()) if w}
        if kind not in held:
            return 0.0
        ws = self.cfg.weapon(kind) or {}
        if stat == "damage":
            return (mul - 1.0 + add / max(1.0, float(ws.get("damage", 45.0)))) \
                * tuning.UPG_WEAPON_HP
        if stat == "cooldown":
            if kind == "gun":
                before = shots_per_s(float(ws.get("cooldown", 0.24)))
                after = shots_per_s(float(ws.get("cooldown", 0.24)) * mul)
                return (after / max(1e-6, before) - 1.0) * tuning.UPG_WEAPON_HP
            return (1.0 / mul - 1.0) * tuning.UPG_WEAPON_HP
        if stat == "speed":
            return (mul - 1.0) * tuning.UPG_RANGE_HP * 0.5
        if stat == "range":
            return (mul - 1.0) * tuning.UPG_RANGE_HP
        if stat == "mag":
            return add * 10.0
        if stat == "reload":
            return (1.0 - mul) * tuning.UPG_MAG_HP
        if stat == "charge":
            return (1.0 - mul) * tuning.UPG_LASER_CHARGE_HP
        if stat in ("splash", "knock", "drain", "gravity"):
            return tuning.UPG_MORTAR_HP
        if stat in ("pierce", "chain", "cone", "energy_cost"):
            return tuning.UPG_WEAPON_HP * 0.3
        if stat in ("spread_deg",):
            return tuning.UPG_WEAPON_HP * 0.2
        return tuning.UPG_UNKNOWN_HP
