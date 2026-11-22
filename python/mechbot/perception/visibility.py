"""Our approximation of the server's vision predicate."""
from __future__ import annotations

from typing import Any, Dict, Optional

from mechbot.config import Config
from mechbot.geometry import angle_diff, bearing, dist2, dist3
from mechbot.perception.model import AgentTrack


def eye_visible(
    me: Dict[str, Any], track: AgentTrack, los, cfg: Config
) -> bool:
    if track.pos is None:
        return False
    pos = me["pos"]
    stats = me.get("stats") or {}
    eye_h = float(stats.get("eye_height", cfg.eye_height))
    eye = (pos[0], pos[1], pos[2] + eye_h)

    cubes = track.cubes or 0
    scale = 1.0 + cfg.size_per_cube * cubes
    center = (track.pos[0], track.pos[1], track.pos[2] + 0.5 * cfg.height * scale)
    top = (track.pos[0], track.pos[1], track.pos[2] + cfg.height * scale)

    d3 = dist3(pos, track.pos)
    if d3 <= cfg.near_range:
        if (not los.sight(eye, center)) or (not los.sight(eye, top)):
            return True

    d2 = dist2(pos, track.pos)
    if d2 <= cfg.vision_range:
        aim = me.get("aim") or (0.0, 0.0)
        brg = bearing(pos[0], pos[1], track.pos[0], track.pos[1])
        if abs(angle_diff(brg, float(aim[0]))) <= 0.5 * cfg.fov_deg * 0.017453292519943295:
            if (not los.sight(eye, center)) or (not los.sight(eye, top)):
                return True
    return False
