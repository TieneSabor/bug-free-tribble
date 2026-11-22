"""Test support: real hello config and synthetic observations."""
from __future__ import annotations

import gzip
import json
import os
import sys
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
PYDIR = os.path.dirname(HERE)
ROOT = os.path.dirname(PYDIR)
if PYDIR not in sys.path:
    sys.path.insert(0, PYDIR)

from mechbot.config import Config  # noqa: E402


def load_hello() -> Dict[str, Any]:
    path = os.path.join(ROOT, "check", "stream.jsonl.gz")
    with gzip.open(path, "rt") as f:
        for line in f:
            m = json.loads(line)
            if m.get("type") == "hello":
                m.setdefault("map", {})["dir"] = os.path.join(ROOT, "arena")
                return m
    raise RuntimeError("no hello in stream")


def make_me(
    x: float = 0.0,
    y: float = 0.0,
    z: float = 0.0,
    yaw: float = 0.0,
    hp: float = 1400.0,
    ammo: Optional[int] = 12,
) -> Dict[str, Any]:
    weapon = None
    if ammo is not None:
        weapon = {
            "kind": "gun",
            "cooldown": 0.0,
            "ammo": ammo,
            "reload": 0.0,
            "stats": {
                "damage": 45,
                "cooldown": 0.24,
                "speed": 252,
                "range": 230,
                "spread_deg": 0.6,
                "mag": 12,
                "reload": 2.4,
            },
        }
    return {
        "id": 0,
        "pos": [x, y, z],
        "vel": [0.0, 0.0, 0.0],
        "aim": [yaw, 0.0],
        "hp": hp,
        "max_hp": 1400.0,
        "energy": 100.0,
        "max_energy": 100.0,
        "grounded": True,
        "cubes": 0,
        "upgrades": [],
        "weapons": [weapon, None],
        "in_zone": True,
        "stats": {
            "walk_speed": 11.7,
            "boost_speed": 19.5,
            "turn_rate": 4.0,
            "muzzle_height": 7.0,
            "eye_height": 8.0,
            "radius": 2.5,
            "height": 9.0,
        },
    }


def make_zone(
    t: float = 0.0,
    center: Optional[List[float]] = None,
    radius: float = 560.0,
    next_center: Optional[List[float]] = None,
    next_radius: float = 380.0,
    shrink_start: float = 60.0,
    shrink_end: float = 110.0,
    dps: float = 20.0,
) -> Dict[str, Any]:
    return {
        "center": center or [0.0, 0.0],
        "radius": radius,
        "next_center": next_center or [0.0, 0.0],
        "next_radius": next_radius,
        "shrink_start": shrink_start,
        "shrink_end": shrink_end,
        "dps": dps,
    }


def make_mech(
    ident: int = 5,
    x: float = 30.0,
    y: float = 0.0,
    z: float = 0.0,
    hp: float = 1400.0,
    weapons: Optional[List[str]] = None,
    charging: bool = False,
) -> Dict[str, Any]:
    return {
        "id": ident,
        "kind": "mech",
        "pos": [x, y, z],
        "vel": [0.0, 0.0, 0.0],
        "aim": [3.14159, 0.0],
        "hp": hp,
        "max_hp": 1400.0,
        "cubes": 0,
        "weapons": weapons or ["gun"],
        "charging": charging,
    }


def make_obs(
    t: float = 0.0,
    tick: float = 0.0,
    me: Optional[Dict[str, Any]] = None,
    zone: Optional[Dict[str, Any]] = None,
    mechs: Optional[List[Dict[str, Any]]] = None,
    events: Optional[List[Dict[str, Any]]] = None,
    projectiles: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return {
        "type": "obs",
        "tick": tick,
        "t": t,
        "alive": 16,
        "self": me or make_me(),
        "mechs": mechs or [],
        "projectiles": projectiles or [],
        "crates": [],
        "cubes": [],
        "pickups": [],
        "sounds": [],
        "beams": [],
        "events": events or [],
        "zone": zone or make_zone(t),
        "offer": None,
        "drops": [],
    }


def load_config() -> Config:
    return Config(load_hello())
