"""Dataclasses shared by tracking and the battlefield facade."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

Vec3 = Tuple[float, float, float]
Vec2 = Tuple[float, float]


@dataclass
class AgentTrack:
    id: int
    kind: str = "mech"
    slot: Optional[int] = None

    pos: Optional[Vec3] = None
    vel: Optional[Vec3] = None
    aim: Optional[Vec2] = None
    charging: bool = False
    charge_start: Optional[float] = None

    hp: Optional[float] = None
    max_hp: Optional[float] = None
    cubes: Optional[int] = None
    weapons: Tuple[str, ...] = ()
    weapons_seen_t: Dict[str, float] = field(default_factory=dict)

    first_t: float = 0.0
    last_listed_t: float = 0.0
    last_visible_t: float = -1e9
    status: str = "remembered"
    confidence: float = 1.0
    dead: bool = False

    last_damaged_us_t: Optional[float] = None
    last_damage_bearing: Optional[float] = None
    last_damage_weapon: Optional[str] = None
    damage_us_total: float = 0.0

    last_fire_t: Optional[float] = None
    last_fire_kind: Optional[str] = None
    last_known_in_zone: Optional[bool] = None
    pos_source: str = "obs"
    last_pos_jump_m: float = 0.0

    @property
    def hp_frac(self) -> Optional[float]:
        if self.hp is None or not self.max_hp:
            return None
        return max(0.0, min(1.0, self.hp / self.max_hp))


@dataclass
class Contact:
    bearing: float
    dist: str
    kind: str
    t: float
