"""What a mode wants to do. No protocol fields live here."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class Intent:
    move: Tuple[float, float] = (0.0, 0.0)
    boost: bool = False
    jump: bool = False
    aim: Tuple[float, float] = (0.0, 0.0)
    fire: Tuple[bool, bool] = (False, False)
    reload: bool = False
    take: Optional[int] = None
    drop: Optional[int] = None
    pick: Optional[int] = None
    label: str = ""
