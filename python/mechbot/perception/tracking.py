"""The mutable agent registry; returns an immutable-per-tick Battlefield view."""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from mechbot import tuning
from mechbot.config import Config
from mechbot.geometry import bearing, dist2, dist3
from mechbot.perception.battlefield import Battlefield
from mechbot.perception.items import ItemMemory
from mechbot.perception.model import AgentTrack, Contact
from mechbot.perception.visibility import eye_visible


class Perception:
    def __init__(self, cfg: Config, los):
        self.cfg = cfg
        if hasattr(los, "sight"):
            self.los = los
        else:
            from mechbot.world.los import MapLos
            self.los = MapLos(los)
        self.mapmodel = los
        self.tracks: Dict[int, AgentTrack] = {}
        self.contacts: List[Contact] = []
        self.projectiles: List[Dict[str, Any]] = []
        self.items = ItemMemory(cfg, visible=self._can_see_item)
        self.offer: Optional[Dict[str, Any]] = None
        self.alive = 16
        self.t = 0.0
        self.tick = 0.0
        self.me: Dict[str, Any] = {}
        self.zone: Dict[str, Any] = {}
        self.last_damage_bearing: Optional[float] = None
        self.last_damage_t = -1e9
        self.last_damage_weapon: Optional[str] = None

    # --- lifecycle -------------------------------------------------------
    def _new_track(self, ident: int, kind: Optional[str] = None) -> AgentTrack:
        k = kind if kind is not None else ("mech" if 0 <= ident <= 15 else "npc")
        return AgentTrack(
            id=ident,
            kind=k,
            slot=ident if k == "mech" else None,
            first_t=self.t,
            last_listed_t=self.t,
        )

    def _track(self, ident: Optional[int], kind: Optional[str] = None) -> Optional[AgentTrack]:
        if ident is None:
            return None
        ident = int(ident)
        tr = self.tracks.get(ident)
        if tr is None:
            tr = self._new_track(ident, kind)
            self.tracks[ident] = tr
        return tr

    # --- update ----------------------------------------------------------
    def update(self, obs: Dict[str, Any]) -> Battlefield:
        self.t = float(obs.get("t", 0.0))
        self.tick = float(obs.get("tick", 0.0))
        self.me = obs.get("self", {})
        self.zone = obs.get("zone", {})
        self.projectiles = list(obs.get("projectiles", []))
        self.offer = obs.get("offer")
        self.alive = int(obs.get("alive", 16) or 16)
        self.items.update(obs, self.t)

        self._prune()

        listed: List[AgentTrack] = []
        for m in obs.get("mechs", []):
            ident = int(m.get("id", -1))
            if ident < 0:
                continue
            tr = self._track(ident, str(m.get("kind", "mech")))
            if tr is None:
                continue
            pos = m.get("pos")
            if pos is not None and tr.pos is not None:
                jump = dist3(tr.pos, pos)
                if jump > tuning.ID_JUMP_M:
                    tr.last_pos_jump_m = jump
                    tr.weapons_seen_t.clear()
                tr.pos = (float(pos[0]), float(pos[1]), float(pos[2]))
            elif pos is not None:
                tr.pos = (float(pos[0]), float(pos[1]), float(pos[2]))
            vel = m.get("vel")
            if vel is not None:
                tr.vel = (float(vel[0]), float(vel[1]), float(vel[2]))
            aim = m.get("aim")
            if aim is not None:
                tr.aim = (float(aim[0]), float(aim[1]))
            was = tr.charging
            tr.charging = bool(m.get("charging", False))
            if tr.charging and not was:
                tr.charge_start = self.t
            elif not tr.charging:
                tr.charge_start = None
            tr.hp = float(m["hp"]) if self.cfg.show_enemy_hp and m.get("hp") is not None else None
            tr.max_hp = (
                float(m["max_hp"])
                if self.cfg.show_enemy_hp and m.get("max_hp") is not None
                else None
            )
            tr.cubes = int(m["cubes"]) if m.get("cubes") is not None else None
            tr.weapons = tuple(str(w) for w in (m.get("weapons") or ()))
            tr.last_listed_t = self.t
            tr.pos_source = "obs"
            if tr.status == "lost":
                tr.status = "remembered"
            listed.append(tr)

        # Our own LOS is the expensive part; cap the nearest, but always
        # re-check anything that was visible last tick so a current target
        # cannot fall out of the cap and be dropped.
        listed.sort(key=lambda a: dist3(self.me.get("pos", (0, 0, 0)), a.pos) if a.pos else 1e9)
        check = listed[: tuning.LOS_CANDIDATES]
        seen = {a.id for a in check}
        for tr in listed:
            if tr.status == "visible" and tr.id not in seen:
                check.append(tr)
                seen.add(tr.id)
        for tr in check:
            if eye_visible(self.me, tr, self.los, self.cfg):
                tr.status = "visible"
                tr.last_visible_t = self.t
                tr.confidence = 1.0
            else:
                tr.status = "remembered"
                tr.confidence = 1.0

        for tr in self.tracks.values():
            if tr.last_listed_t < self.t:
                if self.t - tr.last_listed_t > tuning.MEMORY_GRACE_S:
                    if tr.status != "lost":
                        tr.status = "lost"
                    age = self.t - tr.last_listed_t
                    tr.confidence = max(0.0, 1.0 - age / tuning.CONFIDENCE_HALF_LIFE_S * 0.5)

        self._events(obs)
        self._beams(obs)
        self._sounds(obs)

        return Battlefield(
            t=self.t,
            tick=self.tick,
            me=self.me,
            zone=self.zone,
            tracks=self.tracks,
            contacts=self.contacts,
            projectiles=self.projectiles,
            los=self.los,
            cfg=self.cfg,
            last_damage_bearing=self.last_damage_bearing,
            last_damage_t=self.last_damage_t,
            last_damage_weapon=self.last_damage_weapon,
            items=self.items,
            offer=self.offer,
            alive=self.alive,
        )

    # --- evidence --------------------------------------------------------
    def _events(self, obs: Dict[str, Any]) -> None:
        for ev in obs.get("events", []):
            typ = ev.get("type")
            if typ == "damaged":
                brg = ev.get("bearing")
                wep = ev.get("weapon")
                self.last_damage_bearing = float(brg) if brg is not None else None
                self.last_damage_t = self.t
                self.last_damage_weapon = str(wep) if wep is not None else None
                by = ev.get("by")
                if by is None:
                    continue
                tr = self._track(int(by))
                if tr is None:
                    continue
                tr.last_damaged_us_t = self.t
                tr.last_damage_bearing = float(brg) if brg is not None else None
                tr.last_damage_weapon = str(wep) if wep is not None else None
                try:
                    tr.damage_us_total += float(ev.get("amount", 0.0))
                except (TypeError, ValueError):
                    pass
            elif typ == "kill":
                tr = self.track(int(ev.get("target", -1)))
                if tr is not None:
                    tr.dead = True
                    tr.status = "lost"
                    tr.pos = None
            elif typ == "effect":
                pass
            elif typ == "hit":
                pass

    def _beams(self, obs: Dict[str, Any]) -> None:
        for b in obs.get("beams", []):
            by = b.get("by")
            if by is None:
                continue
            tr = self._track(int(by))
            if tr is None:
                continue
            tr.last_fire_t = self.t
            tr.last_fire_kind = str(b.get("kind", ""))
            if tr.last_fire_kind:
                tr.weapons_seen_t[tr.last_fire_kind] = self.t
            path = b.get("path") or []
            if tr.pos is None and path:
                p0 = path[0]
                yaw = 0.0
                if len(path) > 1:
                    yaw = math.atan2(float(path[1][1]) - float(p0[1]), float(path[1][0]) - float(p0[0]))
                cubes = tr.cubes or 0
                mh = self.cfg.muzzle_height * (1.0 + self.cfg.size_per_cube * cubes)
                tr.pos = (
                    float(p0[0]) - 3.0 * math.cos(yaw),
                    float(p0[1]) - 3.0 * math.sin(yaw),
                    float(p0[2]) - mh,
                )
                tr.pos_source = "beam"
                tr.status = "lost"

    def _sounds(self, obs: Dict[str, Any]) -> None:
        for s in obs.get("sounds", []):
            try:
                self.contacts.append(
                    Contact(
                        bearing=float(s.get("bearing", 0.0)),
                        dist=str(s.get("dist", "far")),
                        kind=str(s.get("kind", "")),
                        t=self.t - float(s.get("age", 0.0)),
                    )
                )
            except (TypeError, ValueError):
                continue
        if len(self.contacts) > tuning.MAX_CONTACTS:
            self.contacts = self.contacts[-tuning.MAX_CONTACTS :]

    def _prune(self) -> None:
        self.contacts = [c for c in self.contacts if self.t - c.t <= tuning.CONTACT_TTL_S]
        dead: List[int] = []
        for ident, tr in self.tracks.items():
            if tr.dead:
                if self.t - tr.last_listed_t > 1.0:
                    dead.append(ident)
            elif self.t - tr.last_listed_t > tuning.LOST_KEEP_S:
                dead.append(ident)
        for ident in dead:
            self.tracks.pop(ident, None)
        if len(self.tracks) > tuning.MAX_TRACKS:
            order = sorted(
                self.tracks.values(),
                key=lambda a: (a.status != "lost", a.last_listed_t),
            )
            for tr in order[: len(self.tracks) - tuning.MAX_TRACKS]:
                self.tracks.pop(tr.id, None)

    # --- helpers ---------------------------------------------------------
    def _can_see_item(self, pos) -> bool:
        """Our eye-to-point sight test, for 'it vanished from view' evidence."""
        p = (self.me or {}).get("pos")
        if not p:
            return False
        try:
            eye_h = float((self.me.get("stats") or {}).get(
                "eye_height", self.cfg.eye_height))
            return not self.los.sight((p[0], p[1], p[2] + eye_h),
                                      (pos[0], pos[1], pos[2] + 0.5))
        except Exception:  # noqa: BLE001 - LOS is advisory here
            return False

    def track(self, ident: Optional[int]) -> Optional[AgentTrack]:
        if ident is None:
            return None
        return self.tracks.get(int(ident))
