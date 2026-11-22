"""Read hello.config once and expose derived values with safe defaults."""
from __future__ import annotations

from typing import Any, Dict, Optional


def _f(d: Dict[str, Any], key: str, default: float) -> float:
    try:
        return float(d.get(key, default))
    except (TypeError, ValueError):
        return default


class Config:
    def __init__(self, hello: Dict[str, Any]):
        c = hello.get("config", {})
        self.raw = c
        self.mech: Dict[str, Any] = c.get("mech", {})
        self.vision: Dict[str, Any] = c.get("vision", {})
        self.sound: Dict[str, Any] = c.get("sound", {})
        self.weapons: Dict[str, Any] = c.get("weapons", {})
        self.projectile: Dict[str, Any] = c.get("projectile", {})
        self.cubes: Dict[str, Any] = c.get("cubes", {})
        self.loot: Dict[str, Any] = c.get("loot", {})
        self.zone: Dict[str, Any] = c.get("zone", {})
        self.match: Dict[str, Any] = c.get("match", {})
        self.debug: Dict[str, Any] = c.get("debug", {})

        self.radius = _f(self.mech, "radius", 2.5)
        self.height = _f(self.mech, "height", 9.0)
        self.eye_height = _f(self.mech, "eye_height", 8.0)
        self.muzzle_height = _f(self.mech, "muzzle_height", 7.0)
        self.walk_speed = _f(self.mech, "walk_speed", 11.7)
        self.boost_speed = _f(self.mech, "boost_speed", 19.5)
        self.ground_accel = _f(self.mech, "ground_accel", 58.5)
        self.jump_speed = _f(self.mech, "jump_speed", 11.0)
        self.turn_rate = _f(self.mech, "turn_rate", 4.0)
        self.pitch_rate = _f(self.mech, "pitch_rate", 3.0)
        self.min_pitch = _f(self.mech, "min_pitch", -0.7)
        self.max_pitch = _f(self.mech, "max_pitch", 1.3)
        self.step_up = _f(self.mech, "step_up", 1.2)
        self.max_slope_deg = _f(self.mech, "max_slope_deg", 50.0)
        self.max_hp = _f(self.mech, "hp", 1400.0)
        self.energy = _f(self.mech, "energy", 100.0)
        self.boost_drain = _f(self.mech, "boost_drain", 17.0)
        self.energy_regen = _f(self.mech, "energy_regen", 18.0)
        self.energy_regen_delay = _f(self.mech, "energy_regen_delay", 0.6)
        self.gravity = _f(self.mech, "gravity", 22.0)
        self.jet_accel = _f(self.mech, "jet_accel", 34.0)
        self.max_rise_speed = _f(self.mech, "max_rise_speed", 10.0)
        self.jet_drain = _f(self.mech, "jet_drain", 15.0)
        self.regen_delay = _f(self.mech, "regen_delay", 5.0)
        self.regen_per_s = _f(self.mech, "regen_per_s", 45.0)
        self.charge_move_mult = _f(self.mech, "charge_move_mult", 0.5)
        self.rear_mult = _f(self.mech, "rear_mult", 1.5)
        self.front_arc_deg = _f(self.mech, "front_arc_deg", 180.0)
        self.npcs: Dict[str, Any] = c.get("npc", {})
        self.crates: Dict[str, Any] = c.get("crates", {})
        self.drops: Dict[str, Any] = c.get("drops", {})
        self.upgrades: Dict[str, Any] = c.get("upgrades", {})

        self.vision_range = _f(self.vision, "range", 200.0)
        self.fov_deg = _f(self.vision, "fov_deg", 120.0)
        self.near_range = _f(self.vision, "near_range", 45.0)
        self.memory_s = _f(self.vision, "memory_s", 5.0)
        self.show_enemy_hp = bool(self.vision.get("show_enemy_hp", True))

        self.gun_radius = _f(self.projectile, "gun_radius", 0.3)
        self.size_per_cube = _f(self.cubes, "size_per_cube", 0.05)
        self.damage_per_cube = _f(self.cubes, "damage_per_cube", 0.04)
        self.stat_cap = _f(self.cubes, "stat_cap", 10.0)
        self.pickup_radius = _f(self.loot, "pickup_radius", 4.0)

        self.zone_start_center = tuple(self.zone.get("start_center", (0.0, 0.0)))
        self.zone_start_radius = _f(self.zone, "start_radius", 560.0)
        self.zone_phases = list(self.zone.get("phases", []))

    def weapon(self, kind: str) -> Dict[str, Any]:
        return self.weapons.get(kind, {})

    def stats_for(self, me: Dict[str, Any]) -> Dict[str, Any]:
        """Per-match stats override mech values (cubes/upgrades)."""
        st = dict(self.mech)
        st.update(me.get("stats") or {})
        return st
