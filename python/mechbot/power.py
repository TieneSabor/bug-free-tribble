"""Threat-weighted strength: expected sustained DPS at a range band.

One function for both sides on purpose: comparing our power with theirs in the
same units is the whole point. Numbers are *effective* (hit rate and duty cycle
included), not nameplate DPS, and they are read from `hello.config`.

Balance data behind the hit rates:
- gun 45 dmg, 0.24 s cooldown, 12-round mag + 2.4 s reload, ~71 % measured hit
  rate at 66.9 % duty cycle  =>  3.33 rds/s * 45 * 0.5 ~= 75 dps effective;
- laser 315 at full charge, 0.75 s charge + 1.65 s cooldown, 97 % conditional
  accuracy  =>  315 / 2.4 * 0.7 ~= 92 dps, but only while it can charge unseen;
- lightning 60 per 0.25 s inside 45 m, 30 deg cone, energy-limited (3/shot).
"""
from __future__ import annotations

import math
from typing import Iterable, Optional, Sequence

# Fraction of the nominal rate a weapon achieves in practice (accuracy x duty).
HIT_RATE = {
    "gun": 0.50,
    "laser": 0.70,
    "lightning": 0.80,
    "mortar": 0.45,
    "npc": 0.55,
}


def weapon_dps(cfg, kind: str, dist: float) -> float:
    """Sustained effective DPS of `kind` against a target at `dist` metres."""
    ws = cfg.weapon(kind) or {}
    if not ws:
        return 0.0
    rng = float(ws.get("range", 0.0))
    if rng > 0.0 and dist > rng:
        return 0.0
    rate = HIT_RATE.get(kind, 0.5)
    if kind == "gun":
        cd = max(0.1, float(ws.get("cooldown", 0.24)))
        mag = max(1.0, float(ws.get("mag", 12)))
        reload_s = max(0.0, float(ws.get("reload", 2.4)))
        # the server fires on the first tick of a decision: 0.1 s grid
        shots_s = 1.0 / max(cd, 0.3)
        duty = (mag * cd) / max(1e-6, mag * cd + reload_s)
        return float(ws.get("damage", 45.0)) * shots_s * duty * rate
    if kind == "laser":
        cycle = max(0.3, float(ws.get("charge", 0.75)) + float(ws.get("cooldown", 1.65)))
        return float(ws.get("damage", 315.0)) / cycle * rate
    if kind == "lightning":
        cd = max(0.1, float(ws.get("cooldown", 0.25)))
        return float(ws.get("damage", 60.0)) / max(cd, 0.3) * rate
    if kind == "mortar":
        cd = max(0.5, float(ws.get("cooldown", 1.0)))
        splash = float(ws.get("damage", 200.0)) + 0.5 * float(ws.get("splash", 160.0))
        return splash / cd * rate
    return 0.0


def loadout_dps(cfg, kinds: Iterable[str], dist: float) -> float:
    """Best sustained DPS a mech holding `kinds` can apply at `dist`."""
    best = 0.0
    for kind in kinds or ():
        if not kind:
            continue
        best = max(best, weapon_dps(cfg, str(kind), dist))
    return best


def held_kinds(me: dict) -> tuple:
    out = []
    for w in me.get("weapons") or ():
        if not w:
            continue
        if isinstance(w, str):
            out.append(w)
        else:
            out.append(str(w.get("kind") or ""))
    return tuple(k for k in out if k)


def power(cfg, hp_frac: float, cubes: int, kinds: Sequence[str],
          dist: float) -> float:
    """Expected hostile DPS: health, damage scaling and loadout at range."""
    cap = float(getattr(cfg, "stat_cap", 10.0))
    dmg_mul = 1.0 + float(getattr(cfg, "damage_per_cube", 0.04)) * min(max(0, cubes), cap)
    return max(0.0, min(1.0, hp_frac)) * loadout_dps(cfg, kinds, dist) * dmg_mul


def our_power(cfg, me: dict, dist: float) -> float:
    mhp = float(me.get("max_hp") or cfg.max_hp)
    hp = float(me.get("hp", mhp))
    return power(cfg, hp / max(1.0, mhp), int(me.get("cubes") or 0),
                 held_kinds(me), dist)


def ttk(cfg, hp: float, dps: float) -> float:
    return hp / dps if dps > 1e-6 else math.inf
