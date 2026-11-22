"""Arbitration: clocks -> feasibility -> mode -> movement -> aim/fire."""
from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional, Sequence, Tuple

from mechbot import power as pw
from mechbot import tuning
from mechbot.action.intent import Intent
from mechbot.config import Config
from mechbot.decision.combat import Combat
from mechbot.decision.explore import ExplorePlanner
from mechbot.decision.loot import Pick, LootChooser
from mechbot.decision.upgrades import UpgradePolicy
from mechbot.geometry import angle_diff, clamp, dist2, dist3, normalize2
from mechbot.world.field import Field
from mechbot.world.localplan import LocalPlan
from mechbot.world.roadmap import Roadmap

UNSTUCK, DODGE, RECOVERY, MUST, DISENGAGE, COVER, LOOT, FIGHT, MOVE, HOLD, EXPLORE = range(11)
NAMES = {UNSTUCK: "unstuck", DODGE: "dodge", RECOVERY: "recovery", MUST: "must",
         DISENGAGE: "disengage", COVER: "cover", LOOT: "loot", FIGHT: "fight",
         MOVE: "move", HOLD: "hold", EXPLORE: "explore"}

DWELL = 0.5
TAU_LASER = 0.15
COVER_RADIUS = 60.0


class Arbiter:
    def __init__(self, cfg: Config, road: Roadmap, field: Field, local: LocalPlan,
                 combat: Combat, los, rng: random.Random, strength=None):
        self.cfg = cfg
        self.road = road
        self.field = field
        self.local = local
        self.combat = combat
        self.los = los
        self.rng = rng
        self.strength = strength
        self.dis_goal: Optional[Tuple[float, float]] = None
        self.dis_t = -1e9
        self.dis_entered = -1e9
        self.dis_cap_until = -1e9
        self.loot = LootChooser(cfg)
        self.upgrades = UpgradePolicy(cfg)
        self.explore = ExplorePlanner(cfg, road, field)
        self.loot_pick: Optional[Pick] = None
        self.explore_goal: Optional[Tuple[float, float]] = None
        self.mode = HOLD
        self.entered = -1e9
        self.path: List[Tuple[float, float, float, int]] = []
        self.path_goal: Tuple[float, float] = (0.0, 0.0)
        self.path_t = -1e9
        self.cover_node = -1
        self.cover_t = -1e9
        self.field_t = -1e9
        self.stuck = 0.0
        self.last_pos: Optional[Tuple[float, float, float]] = None
        self.last_t = -1e9
        self.unstuck_until = -1e9
        self.unstuck_dir = (1.0, 0.0)
        self.strafe = 1.0
        self.strafe_until = 0.0
        self.debug = ""
        self.zone_goal: Optional[Tuple[float, float]] = None
        self.zone_goal_t = -1e9
        self.hold_node = -1
        self.hold_t = -1e9
        self.last_move = (0.0, 0.0)
        self.last_move_t = -1e9
        self.commit_until = -1e9
        self.goal_dist = None
        self.goal_dist_t = 0.0
        self.laser_cover = None
        self.laser_cover_t = -1e9
        self.peek_hide = False
        self.peek_t = -1e9
        self.peek_goal = None
        self.peek_goal_t = -1e9
        self.fight_strafe = 1.0
        self.fight_strafe_until = 0.0
        self.fight_cover_dir = (0.0, 0.0)
        self.fight_cover_until = -1e9
        self.target: Optional[Any] = None
        self.target_seen = -1e9
        self._threat_list = []
        self.corridor = []
        self.corridor_key = None
        self.corridor_t = -1e9
        self.corridor_i = 0

    # --- perception helpers -------------------------------------------
    def _threats(self, bf) -> List[Dict[str, Any]]:
        out = []
        me = bf.me.get("pos", (0.0, 0.0, 0.0))
        for t in bf.tracks.values():
            if t.kind != "mech" or t.dead or t.pos is None:
                continue
            age = bf.t - max(t.last_listed_t, t.last_visible_t)
            if age > 2.5:
                continue
            d = dist3(me, t.pos)
            if d > 260.0:
                continue
            dps = self._dps(t, d)
            if dps <= 0.0:
                continue
            w = 1.0
            if (t.last_damaged_us_t is not None
                    and bf.t - t.last_damaged_us_t < 3.0):
                w = 2.2                     # it is shooting us: cover from it first
            elif t.status == "visible":
                brg = math.atan2(me[1] - t.pos[1], me[0] - t.pos[0])
                if t.aim is not None and abs(angle_diff(float(t.aim[0]), brg)) < 0.4:
                    w = 1.5                 # aimed at us
            else:
                w = 0.6                     # known but not currently engaged
            out.append({
                "x": t.pos[0], "y": t.pos[1], "z": t.pos[2],
                "dps": dps, "dist": d, "sees": t.status == "visible",
                "id": t.id, "w": w,
            })
        out.sort(key=lambda e: e["dist"])
        return out

    def _dps(self, t, d: float) -> float:
        total = 0.0
        for kind in (t.weapons or ()):
            ws = self.cfg.weapon(str(kind))
            rng = float(ws.get("range", 0.0))
            if d > rng:
                continue
            if kind == "gun":
                total += float(ws.get("damage", 20.0)) / max(0.1, float(ws.get("cooldown", 0.24)))
            elif kind == "laser":
                total += float(ws.get("damage", 315.0)) / max(0.5, float(ws.get("charge", 3.0)) + 0.5)
            elif kind == "lightning":
                total += float(ws.get("damage", 60.0)) / max(0.1, float(ws.get("cooldown", 0.25)))
            else:
                total += 40.0
        return total * 0.5

    def _tta(self, bf, threats) -> float:
        me = bf.me.get("pos", (0.0, 0.0, 0.0))
        radius = float((bf.me.get("stats") or {}).get("radius", self.cfg.radius))
        tta = 1e9
        for pr in bf.projectiles:
            pos = pr.get("pos")
            vel = pr.get("vel")
            if not pos or not vel:
                continue
            rx = pos[0] - me[0]
            ry = pos[1] - me[1]
            rz = pos[2] - (me[2] + 4.0)
            vx, vy, vz = float(vel[0]), float(vel[1]), float(vel[2])
            v2 = vx * vx + vy * vy + vz * vz
            if v2 < 1.0:
                continue
            tc = -(rx * vx + ry * vy + rz * vz) / v2
            if tc <= 0.0 or tc > 0.7:
                continue
            mx = rx + vx * tc
            my = ry + vy * tc
            if math.hypot(mx, my) <= radius + 1.0:
                tta = min(tta, tc)
        charge = float(self.cfg.weapon("laser").get("charge", 3.0))
        for t in bf.tracks.values():
            if t.kind != "mech" or not t.charging or t.pos is None or t.aim is None:
                continue
            if t.status != "visible":
                continue
            brg = math.atan2(me[1] - t.pos[1], me[0] - t.pos[0])
            if abs(angle_diff(float(t.aim[0]), brg)) < TAU_LASER:
                spent = 0.0 if t.charge_start is None else max(0.0, bf.t - t.charge_start)
                tta = min(tta, max(0.2, charge - spent + 0.15))
        return tta

    def _dodge_vec(self, bf) -> Tuple[float, float]:
        me = bf.me.get("pos", (0.0, 0.0, 0.0))
        dx = dy = 0.0
        for pr in bf.projectiles:
            pos, vel = pr.get("pos"), pr.get("vel")
            if not pos or not vel:
                continue
            vx, vy = float(vel[0]), float(vel[1])
            vh = math.hypot(vx, vy)
            if vh < 1.0:
                continue
            rx, ry = pos[0] - me[0], pos[1] - me[1]
            tc = -(rx * vx + ry * vy) / (vh * vh)
            if tc <= 0.0 or tc > 0.7:
                continue
            mx, my = rx + vx * tc, ry + vy * tc
            if math.hypot(mx, my) > self.cfg.radius + 1.0:
                continue
            px, py = -vy / vh, vx / vh
            if px * rx + py * ry > 0.0:
                px, py = -px, -py
            dx += px
            dy += py
        if abs(dx) + abs(dy) < 1e-6:
            for t in bf.tracks.values():
                if t.kind != "mech" or not t.charging or t.pos is None or t.aim is None:
                    continue
                if t.status != "visible":
                    continue
                brg = math.atan2(me[1] - t.pos[1], me[0] - t.pos[0])
                if abs(angle_diff(float(t.aim[0]), brg)) < TAU_LASER:
                    dx += math.cos(brg + math.pi / 2.0) * self.strafe
                    dy += math.sin(brg + math.pi / 2.0) * self.strafe
        return normalize2(dx, dy)

    def _update_strafe(self, bf) -> None:
        if bf.t >= self.strafe_until:
            if self.rng.random() < 0.6:
                self.strafe = -self.strafe
            self.strafe_until = bf.t + 0.3 + self.rng.random() * 0.7

    # --- path service --------------------------------------------------
    def _path(self, bf, goal, threats) -> Sequence[Tuple[float, float, float, int]]:
        now = bf.t
        if now < self.commit_until and self.path:
            return self.path
        gx, gy = goal
        moved = math.hypot(gx - self.path_goal[0], gy - self.path_goal[1])
        if not self.path or moved > 6.0 or now - self.path_t > 0.8:
            me = bf.me
            hp = float(me.get("hp", self.cfg.max_hp))
            mhp = max(1.0, float(me.get("max_hp", self.cfg.max_hp)))
            hard = hp / mhp < 0.5 or self._laser_carrier(bf)
            self.path = self.local.plan(
                me["pos"][0], me["pos"][1], me["pos"][2], (gx, gy),
                [(t["x"], t["y"], t["z"], t["dps"], t["w"]) for t in threats],
                bf.zone, now, hard,
            )
            self.path_goal = (gx, gy)
            self.path_t = now
        return self.path

    def _zone_goal(self, bf, pos, now: float, zone: dict) -> Tuple[float, float]:
        """Keep the field's next pointer stable for 0.8 s.

        Snapping can jump between two main-component nodes 2 m apart whose
        next[] pointers lead opposite ways around a building; without this the
        bot dithers in place while the zone closes.
        """
        nc = zone.get("next_center", (0.0, 0.0))
        nr = float(zone.get("next_radius", 0.0))
        stale = (
            self.zone_goal is not None
            and math.hypot(self.zone_goal[0] - nc[0], self.zone_goal[1] - nc[1]) > nr + 60.0
        )
        if self.field.busy or stale:
            # the sliced field is still converging (or the phase moved): head
            # straight for the next centre instead of trusting a half-built next[]
            dx, dy = nc[0] - pos[0], nc[1] - pos[1]
            d = math.hypot(dx, dy)
            if d < 1e-6:
                return (pos[0], pos[1])
            step = min(20.0, d)
            g = (pos[0] + dx / d * step, pos[1] + dy / d * step)
            self.zone_goal = g
            self.zone_goal_t = now
            return g
        if (
            self.zone_goal is not None
            and now - self.zone_goal_t < 2.5
            and math.hypot(self.zone_goal[0] - pos[0], self.zone_goal[1] - pos[1]) > 3.0
        ):
            return self.zone_goal
        g = self.field.next_point(pos[0], pos[1])
        # A* is ~2 ms p50 / 15 ms p99; keep the corridor and walk along it
        # instead of re-planning the graph every couple of seconds
        key = (round(float(zone.get("shrink_start", 0.0)), 1),
               round(float(zone.get("shrink_end", 0.0)), 1),
               round(nc[0]), round(nc[1]), round(nr))
        if key != self.corridor_key or now - self.corridor_t > 6.0:
            a = self.road.snap(pos[0], pos[1])
            b = self.road.snap(nc[0], nc[1])
            self.corridor = self.road.route(a, b) or []
            self.corridor_key = key
            self.corridor_t = now
            self.corridor_i = 0
        if self.corridor:
            i = min(self.corridor_i, len(self.corridor) - 1)
            while (i < len(self.corridor) - 1
                   and math.hypot(self.road.x[self.corridor[i]] - pos[0],
                                  self.road.y[self.corridor[i]] - pos[1]) < 4.0):
                i += 1
            self.corridor_i = i
            acc = 0.0
            px, py = pos[0], pos[1]
            for k in range(i, len(self.corridor)):
                acc += math.hypot(self.road.x[k] - px, self.road.y[k] - py)
                px, py = self.road.x[k], self.road.y[k]
                if acc >= 25.0:
                    g = (px, py)
                    break
            else:
                g = (self.road.x[self.corridor[-1]], self.road.y[self.corridor[-1]])
        self.zone_goal = g
        self.zone_goal_t = now
        self.goal_dist = None
        self.goal_dist_t = now
        return g

    # --- decision ------------------------------------------------------
    def decide(self, bf) -> Intent:
        me = bf.me
        pos = me.get("pos", (0.0, 0.0, 0.0))
        zone = bf.zone
        now = bf.t
        hp = float(me.get("hp", self.cfg.max_hp))
        mhp = max(1.0, float(me.get("max_hp", self.cfg.max_hp)))
        hpf = hp / mhp
        energy = float(me.get("energy", self.cfg.energy))
        grounded = bool(me.get("grounded", True))

        threats = self._threats(bf)
        self._threat_list = threats
        tta = self._tta(bf, threats)
        incoming = sum(t["dps"] for t in threats if t["sees"]) or 0.0
        ttb = (hp - 0.25 * mhp) / max(1.0, incoming) if incoming > 0 else 1e9
        # One target and one solution per decision: movement, aim and fire all
        # use the same lock, and knowing the weapon readiness lets the fight
        # loop hide during reload/cooldown instead of guessing.
        target = self.combat.target(bf)
        sol = self.combat.aim_fire(bf, target) if target is not None else None

        center = zone.get("next_center", (0.0, 0.0))
        nrad = float(zone.get("next_radius", 0.0))
        self.field.ensure(zone, center, max(1.0, nrad), 0.0015)
        slack = self.field.slack(zone, pos, now) if self.field.eta else 0.0
        outside = not bool(me.get("in_zone", False))

        # stuck detection (decisions are 0.1 s apart)
        vel = me.get("vel", (0.0, 0.0, 0.0))
        speed = math.hypot(float(vel[0]), float(vel[1]))

        dodge = self._dodge_vec(bf) if tta <= 0.7 else (0.0, 0.0)
        laser_duck = tta <= 3.2 and self._laser_aimed(bf)
        cover: List[int] = []
        lightning_close = self._lightning_close(bf)
        laser_carrier = self._laser_carrier(bf)
        if (self.strength is not None and tuning.DISENGAGE_ENABLE
                and self.strength.due(now)):
            self.strength.rebuild(bf, now)
        s_local = self._local_strength(pos)
        p_us = pw.our_power(self.cfg, me, 80.0) or 1.0
        # one 520-damage laser is 37% of HP: against a laser carrier, break
        # contact after any hit and heal back to full before re-engaging
        if laser_carrier:
            heal_to = 0.95 if self.mode == COVER else 0.78
        else:
            heal_to = 0.75 if self.mode == COVER else 0.45
        heal_to = self._heal_bias(heal_to, s_local, p_us, hpf, now)
        need_cover = hpf < heal_to or ttb <= 3.0 or lightning_close
        if need_cover and not outside:
            if self.cover_node < 0 or now - self.cover_t > 1.0:
                cover = self.road.cover(
                    pos[0], pos[1], pos[2],
                    [(t["x"], t["y"], t["z"]) for t in threats[:4] if t["sees"]],
                    COVER_RADIUS,
                )
                self.cover_node = cover[0] if cover else -1
                self.cover_t = now
            elif self.cover_node >= 0:
                cover = [self.cover_node]

        if speed < 1.2 and self.path and now >= self.unstuck_until:
            self.stuck += 0.1
        else:
            self.stuck = 0.0

        # --- loot choice (arm 1) ----------------------------------------
        self.loot_pick = None
        loot_urg = 0.0
        if (tuning.LOOT_ENABLE and not outside
                and hpf >= tuning.LOOT_HP_MIN
                and slack > tuning.LOOT_SLACK_MIN_S):
            self.loot_pick = self.loot.select(bf, self.field, now)
            if self.loot_pick is not None:
                loot_urg = (tuning.LOOT_URGENT if self.loot_pick.score >= 1.0
                            else tuning.LOOT_GOOD)

        # --- explore filler (arm 2a) ------------------------------------
        slots = me.get("weapons") or []
        slot1 = slots[1] if len(slots) > 1 else None
        k1 = str(slot1.get("kind") if isinstance(slot1, dict) else (slot1 or ""))
        needs_weapon = slot1 is None or k1 == "mortar"
        self.explore_goal = None
        if (tuning.EXPLORE_ENABLE and needs_weapon and self.loot_pick is None
                and not outside and hpf >= tuning.LOOT_HP_MIN
                and slack > tuning.LOOT_SLACK_MIN_S):
            self.explore_goal = self.explore.update(bf, now)

        # --- disengage (arm 2b) ------------------------------------------
        self.dis_goal = None
        if (self.mode == DISENGAGE
                and now - self.dis_entered > tuning.DIS_MAX_S):
            self.dis_cap_until = now + tuning.DIS_REENTER_S
        if (tuning.DISENGAGE_ENABLE and self.strength is not None and not outside
                and slack > 3.0 and hpf >= tuning.DIS_MIN_HP
                and now >= self.dis_cap_until):
            if self._disengage_entry(bf, threats, hpf, ttb, now, s_local, p_us):
                dis_heal_to = (tuning.DIS_HEAL_TO_LASER if laser_carrier
                               else tuning.DIS_HEAL_TO)
                self.dis_goal = self._disengage_goal(
                    bf, threats, now, pos, hpf, dis_heal_to, p_us)

        # --- mode selection (feasibility first, then clocks) ------------
        if self.stuck > 0.7:
            want = UNSTUCK
        elif (tta <= 0.7 and (abs(dodge[0]) + abs(dodge[1]) > 0.1)) or laser_duck:
            want = DODGE
        elif outside:
            want = RECOVERY
        elif slack <= 0.0:
            want = MUST
        elif self.dis_goal is not None:
            want = DISENGAGE
        elif self.cover_node >= 0 and need_cover:
            want = COVER
        elif loot_urg >= tuning.LOOT_URGENT:
            want = LOOT
        elif slack <= 8.0:
            want = MOVE
        elif self._duel_target(bf, hpf, slack, target) is not None:
            want = FIGHT
        elif loot_urg >= tuning.LOOT_GOOD:
            want = LOOT
        elif slack <= 25.0:
            want = MOVE
        elif self.explore_goal is not None:
            want = EXPLORE
        else:
            want = HOLD

        if want != self.mode:
            higher = want < self.mode
            if higher or now - self.entered >= DWELL or not self._feasible(self.mode, bf):
                self.mode = want
                self.entered = now
                self.path = []
                self.path_t = -1e9
                if want == COVER and self.cover_node < 0:
                    self.cover_node = -1
                if want == DISENGAGE:
                    self.dis_entered = now

        mode = self.mode
        move = (0.0, 0.0)
        jump = False
        boost = False
        label = NAMES[mode]

        if mode == UNSTUCK:
            if now >= self.unstuck_until:
                a = self.rng.random() * 2 * math.pi
                self.unstuck_dir = (math.cos(a), math.sin(a))
                self.unstuck_until = now + 0.8
            move = self.unstuck_dir
            jump = grounded
        elif mode == DODGE:
            move = dodge
            jump = False
            boost = energy > 20.0 and grounded is False
            label = "dodge tta=%.2f" % tta
            # laser telegraph: breaking LOS beats a lateral step
            laser = None
            for t in bf.tracks.values():
                if (t.kind == "mech" and t.charging and t.pos is not None
                        and t.aim is not None and t.status == "visible"):
                    brg = math.atan2(pos[1] - t.pos[1], pos[0] - t.pos[0])
                    if abs(angle_diff(float(t.aim[0]), brg)) < TAU_LASER:
                        laser = t
                        break
            if laser is not None:
                goal = None
                if now >= self.laser_cover_t:
                    self.laser_cover = self.local.find_cover(
                        pos[0], pos[1], pos[2], laser.pos, 15.0)
                    if self.laser_cover is None:
                        nodes = self.road.cover(
                            pos[0], pos[1], pos[2],
                            [(laser.pos[0], laser.pos[1], laser.pos[2])], 25.0)
                        if nodes:
                            self.laser_cover = (self.road.x[nodes[0]], self.road.y[nodes[0]])
                    self.laser_cover_t = now + 0.4
                goal = self.laser_cover
                if goal is not None:
                    path = self._path(bf, goal, threats)
                    mv, jp, bs, _ = self.local.step(path, me, energy, self.cfg.walk_speed)
                    if abs(mv[0]) + abs(mv[1]) < 0.05:
                        mv = normalize2(goal[0] - pos[0], goal[1] - pos[1])
                    move, jump, boost = mv, jp, False
                    label = "duck laser"
        elif mode in (RECOVERY, MUST):
            goal = self._zone_goal(bf, pos, now, zone)
            if goal == (pos[0], pos[1]):
                goal = zone.get("next_center", (0.0, 0.0))
            path = self._path(bf, goal, threats)
            move, jump, boost, sub = self.local.step(path, me, energy, self.cfg.walk_speed)
            if abs(move[0]) + abs(move[1]) < 0.01:
                move = normalize2(goal[0] - pos[0], goal[1] - pos[1])
            boost = boost or (grounded and energy > tuning.BOOST_ENERGY_RESERVE
                              and (outside or slack < 6.0))
            label = "%s slack=%.0f" % (NAMES[mode], slack)
        elif mode == DISENGAGE:
            goal = self.dis_goal or self._zone_goal(bf, pos, now, zone)
            path = self._path(bf, goal, threats)
            move, jump, boost, sub = self.local.step(path, me, energy, self.cfg.walk_speed)
            if abs(move[0]) + abs(move[1]) < 0.01:
                move = normalize2(goal[0] - pos[0], goal[1] - pos[1])
            if now - self.dis_entered > 6.0 and not self._seen_by(bf):
                move = self._cap_silent(bf, move)
            boost = False
            label = "disengage d=%.0f hp=%.0f" % (
                math.hypot(goal[0] - pos[0], goal[1] - pos[1]), hpf * 100.0)
        elif mode == COVER:
            node = self.cover_node
            if node < 0:
                goal = self.field.next_point(pos[0], pos[1])
            else:
                goal = (self.road.x[node], self.road.y[node])
            path = self._path(bf, goal, threats)
            move, jump, boost, sub = self.local.step(path, me, energy, self.cfg.walk_speed)
            if math.hypot(goal[0] - pos[0], goal[1] - pos[1]) < 2.0:
                move = (0.0, 0.0)
            elif abs(move[0]) + abs(move[1]) < 0.01:
                move = normalize2(goal[0] - pos[0], goal[1] - pos[1])
            boost = False
            label = "cover"
        elif mode == LOOT:
            pick = self.loot_pick
            if pick is None:
                goal = self._zone_goal(bf, pos, now, zone)
                label = "loot none"
            else:
                goal = (pick.pos[0], pick.pos[1])
                label = "loot %s d=%.0f" % (self.loot.reason,
                                            math.hypot(goal[0] - pos[0], goal[1] - pos[1]))
            path = self._path(bf, goal, threats)
            move, jump, boost, sub = self.local.step(path, me, energy, self.cfg.walk_speed)
            if math.hypot(goal[0] - pos[0], goal[1] - pos[1]) < 2.5:
                move = (0.0, 0.0)
            elif (pick is not None and pick.kind == "crate"
                  and math.hypot(goal[0] - pos[0], goal[1] - pos[1])
                  <= tuning.CRATE_RANGE_M - 4.0):
                move = (0.0, 0.0)      # in range: stand and shoot it
            elif abs(move[0]) + abs(move[1]) < 0.01:
                move = normalize2(goal[0] - pos[0], goal[1] - pos[1])
            move = self._cap_silent(bf, move)
            boost = False
        elif mode == EXPLORE:
            goal = self.explore_goal or self._zone_goal(bf, pos, now, zone)
            path = self._path(bf, goal, threats)
            move, jump, boost, sub = self.local.step(path, me, energy, self.cfg.walk_speed)
            if abs(move[0]) + abs(move[1]) < 0.01:
                move = normalize2(goal[0] - pos[0], goal[1] - pos[1])
            move = self._cap_silent(bf, move)
            boost = False
            label = "explore %s d=%.0f" % (
                self.explore.reason, math.hypot(goal[0] - pos[0], goal[1] - pos[1]))
        elif mode == FIGHT:
            move, jump, boost, sub = self._fight_move(bf, hpf, target, sol, tta)
            d_fight = (
                math.hypot(target.pos[0] - pos[0], target.pos[1] - pos[1])
                if target is not None and target.pos else -1.0
            )
            label = "fight t%d d=%.0f cd=%.1f%s" % (
                target.id if target is not None else -1,
                d_fight,
                float(sol["next_ready_s"]) if sol is not None else -1.0,
                " cov" if sub == "cov" else "",
            )
        elif mode == MOVE:
            goal = self._zone_goal(bf, pos, now, zone)
            path = self._path(bf, goal, threats)
            move, jump, boost, sub = self.local.step(path, me, energy, self.cfg.walk_speed)
            if abs(move[0]) + abs(move[1]) < 0.01:
                move = normalize2(goal[0] - pos[0], goal[1] - pos[1])
            boost = grounded and energy > tuning.BOOST_ENERGY_RESERVE and slack < 6.0
            label = "move slack=%.0f" % slack
        else:  # HOLD
            goal = self._hold_goal(bf, pos)
            if math.hypot(goal[0] - pos[0], goal[1] - pos[1]) > 6.0:
                path = self._path(bf, goal, threats)
                move, jump, boost, sub = self.local.step(path, me, energy, self.cfg.walk_speed)
                if abs(move[0]) + abs(move[1]) < 0.01:
                    move = normalize2(goal[0] - pos[0], goal[1] - pos[1])
            else:
                move = normalize2(goal[0] - pos[0], goal[1] - pos[1])
            far = math.hypot(goal[0] - pos[0], goal[1] - pos[1]) > 15.0
            if abs(move[0]) + abs(move[1]) > 0.0 and not far:
                move = (move[0] * 0.38, move[1] * 0.38)  # under the step-sound threshold
            label = "hold"

        # --- progress watchdog: break long oscillations ------------------
        if self.zone_goal is not None:
            d = math.hypot(self.zone_goal[0] - pos[0], self.zone_goal[1] - pos[1])
            if self.goal_dist is None or d < self.goal_dist - 4.0:
                self.goal_dist = d
                self.goal_dist_t = now
            elif now - self.goal_dist_t > 4.0:
                # no progress for 4 s while moving: freeze the current path so
                # a mirrored replan cannot undo it
                self.commit_until = now + 1.5
                self.goal_dist = d
                self.goal_dist_t = now

        # --- geometry escape -------------------------------------------
        if not self.local.standable(pos[0], pos[1], pos[2]):
            ex, ey = self.local.escape_dir(pos[0], pos[1], pos[2])
            if abs(ex) + abs(ey) > 0.01:
                move = (ex, ey)
                jump = grounded
                label = "escape"

        # --- turn limiter: no 180-degree flips inside 0.4 s --------------
        covering = bool(mode == FIGHT and sol is not None and sol.get("down"))
        if mode != DODGE and not covering and self.last_move is not None:
            lm = self.last_move
            if (
                now - self.last_move_t < 0.4
                and abs(lm[0]) + abs(lm[1]) > 0.1
                and move[0] * lm[0] + move[1] * lm[1] < 0.0
            ):
                bx, by = normalize2(move[0] * 0.25 + lm[0] * 0.75,
                                    move[1] * 0.25 + lm[1] * 0.75)
                move = (bx, by)

        # --- soft constraints ------------------------------------------
        if mode != DODGE and tta <= 0.7:
            move = normalize2(move[0] + dodge[0] * 0.4, move[1] + dodge[1] * 0.4)
        move = self.local.legalize(move[0], move[1], pos[0], pos[1], zone, pos[2])
        if abs(move[0]) + abs(move[1]) > 0.1:
            self.last_move = move
            self.last_move_t = now

        # --- facing / fire ---------------------------------------------
        crate_aim = None
        if (mode == LOOT and self.loot_pick is not None
                and self.loot_pick.kind == "crate"):
            crate_aim = self._crate_aim(bf, self.loot_pick.pos)
        if crate_aim is not None and target is None:
            aim, fire, reload_req = crate_aim, [True, False], False
        elif target is not None and sol is not None:
            aim = sol["aim"]
            fire = sol["fire"]
            reload_req = sol["reload"]
        else:
            ghost = None
            for t in bf.tracks.values():
                if t.kind == "mech" and not t.dead and t.pos is not None \
                        and t.status == "lost" and t.pos_source == "beam":
                    res = self.combat.ghost_fire(bf, t)
                    if res is not None:
                        ghost = res
                        break
            if ghost is not None:
                aim, fire, reload_req = ghost["aim"], ghost["fire"], False
            else:
                brg = bf.last_damage_bearing(2.0)
                yaw = brg if brg is not None else (
                    math.atan2(move[1], move[0]) if abs(move[0]) + abs(move[1]) > 0.05
                    else float(me.get("aim", (0.0, 0.0))[0]) + 0.35
                )
                aim = self.combat.face(bf, yaw)
                fire = [False, False]
                reload_req = self.combat.idle_reload(bf)

        # regen only starts after `regen_delay` seconds without dealing or
        # taking damage: while disengaging, do not shoot unless the attacker is
        # close enough that the shot is needed to break pursuit.
        if mode == DISENGAGE and not any(
                t["dist"] <= tuning.DIS_FIRE_RANGE_M for t in threats if t["sees"]):
            fire = [False, False]

        nc = zone.get("next_center", (0.0, 0.0))
        take = self.loot.take_id(bf, self.loot_pick, now)
        take_id, drop_slot = take if take else (None, None)
        pick = self.upgrades.choose(getattr(bf, "offer", None), me)
        self.debug = (
            "%s hp=%.0f slack=%.0f eta=%.0f nc=(%.0f,%.0f) "
            "mv=(%.2f,%.2f) g=(%.0f,%.0f) np=%d ch=%d loot=%s"
            % (
                label, hpf * 100.0, slack,
                self.field.eta_at(pos[0], pos[1]),
                nc[0], nc[1],
                move[0], move[1],
                self.zone_goal[0] if self.zone_goal else -1,
                self.zone_goal[1] if self.zone_goal else -1,
                len(self.path),
                sum(1 for t in bf.tracks.values()
                    if t.kind == "mech" and t.charging and t.status == "visible"),
                self.loot.reason if self.loot_pick is not None else "-",
            )
        )
        return Intent(
            move=move, boost=bool(boost and abs(move[0]) + abs(move[1]) > 0.05),
            jump=bool(jump), aim=aim, fire=fire, reload=reload_req,
            take=take_id, drop=drop_slot, pick=pick, label=self.debug,
        )

    # --- disengage / strength helpers ----------------------------------
    def _local_strength(self, pos) -> float:
        if (self.strength is None or not tuning.DISENGAGE_ENABLE
                and not tuning.HEAL_LEDGER_ENABLE and tuning.HOLD_DENSITY_W <= 0.0):
            return 0.0
        try:
            return self.strength.mean_near(pos, tuning.FIGHT_SUPPORT_M)
        except Exception:  # noqa: BLE001 - field is advisory
            return 0.0

    def _heal_bias(self, heal_to: float, s_local: float, p_us: float,
                   hpf: float, now: float) -> float:
        if not tuning.HEAL_LEDGER_ENABLE:
            return heal_to
        """The heal-vs-act ledger, in HP-fraction form.

        Heal earlier when the local field says we are outgunned, later when it
        says we are alone, and always late in the match: survivors are ranked
        by HP at the clock.
        """
        if s_local > p_us:
            heal_to = min(0.90, heal_to + tuning.HEAL_BIAS_STRONG)
        elif s_local < 0.4 * p_us:
            heal_to = min(heal_to, tuning.HEAL_BIAS_QUIET)
        dur = float((self.cfg.match or {}).get("duration_s", 480.0) or 480.0)
        if now > dur - tuning.HEAL_DEADLINE_S and hpf < 0.9:
            heal_to = max(heal_to, 0.9)
        return heal_to

    def _disengage_entry(self, bf, threats, hpf: float, ttb: float,
                         now: float, s_local: float, p_us: float) -> bool:
        attack = [t for t in threats if t["sees"]]
        n_att = 0
        for t in bf.tracks.values():
            if t.kind != "mech" or t.dead or t.last_damaged_us_t is None:
                continue
            if now - t.last_damaged_us_t <= tuning.DIS_MULTI_S:
                n_att += 1
        if ttb < tuning.DIS_TTB_S:
            return True
        if n_att >= 2 and hpf < tuning.DIS_MULTI_HP:
            return True
        if attack and s_local > tuning.DIS_STRENGTH_RATIO * p_us and hpf < 0.85:
            return True
        if attack and hpf < tuning.DIS_WEAK_HP:
            weakest = True
            for t in bf.tracks.values():
                if t.kind != "mech" or t.dead or t.pos is None:
                    continue
                if t.status != "visible":
                    continue
                f = t.hp_frac
                if f is not None and f <= hpf:
                    weakest = False
                    break
            if weakest:
                return True
        return False

    def _zone_ok_dist(self, bf, p, now: float, dist: float) -> bool:
        if not getattr(self.field, "eta", None):
            return True
        try:
            eta = dist * 1.25 / max(1.0, self.cfg.walk_speed) + 2.0
            dl = self.field.deadline(bf.zone, p, now)
        except Exception:  # noqa: BLE001
            return True
        return now + eta <= dl - tuning.DIS_ZONE_MARGIN_S

    def _corridor_hidden(self, bf, pos, goal, hot) -> bool:
        """Hidden along the run, not only at the goal.

        Rivals' deaths while retreating are people shot in the back during the
        run, so the first 40 m and the endpoint both have to break sight.
        """
        dx, dy = goal[0] - pos[0], goal[1] - pos[1]
        dz = goal[2] - pos[2]
        for i, frac in enumerate((0.35, 0.7, 1.0)):
            x = pos[0] + dx * frac
            y = pos[1] + dy * frac
            z = pos[2] + dz * frac
            f = self.local.floor_at(x, y, z)
            if f is None:
                return False
            body = (x, y, f + 4.5)
            for j, h in enumerate(hot[:2]):
                if j == 1 and i < 2:
                    continue
                eye = (h[0], h[1], h[2] + 8.0)
                if not self.los.sight(eye, body):
                    return False
        return True

    def _disengage_goal(self, bf, threats, now: float, pos, hpf: float,
                        heal_to: float, p_us: float):
        last_dmg = getattr(bf, "last_damage_t", -1e9)
        if (hpf >= heal_to and not self._seen_by(bf)
                and now - last_dmg > 4.0):
            return None                      # X1: healed, silent, unseen
        if now - self.dis_t < tuning.DIS_LATCH_S and self.dis_goal is not None:
            return self.dis_goal
        self.dis_t = now
        hot = [(t["x"], t["y"], t["z"]) for t in threats if t["sees"]][:4]
        if not hot:
            return None
        atk = [(t["x"], t["y"], t["z"], t["dps"], t["w"]) for t in threats[:5]]
        nodes = self.road.cover(pos[0], pos[1], pos[2], hot, tuning.DIS_RADIUS_M)
        best, best_score = None, -1e18
        for k in nodes[:12]:
            nx, ny, nz = self.road.node(k)
            d = math.hypot(nx - pos[0], ny - pos[1])
            if d < tuning.DIS_MIN_M or d > tuning.DIS_RADIUS_M:
                continue
            if not self._zone_ok_dist(bf, (nx, ny), now, d):
                continue
            if not self._corridor_hidden(bf, pos, (nx, ny, nz), hot):
                continue
            risk = 0.0
            if self.strength is not None:
                risk = self.strength.path_risk(pos, (nx, ny)) / max(1.0, d)
            dps, nvis = self.local.exposure_at(nx, ny, nz, atk)
            score = (-tuning.DIS_RISK_W * risk
                     - tuning.DIS_DPS_W * dps
                     - 30.0 * nvis
                     - tuning.DIS_DIST_W * d)
            if score > best_score:
                best, best_score = (nx, ny), score
        return best

    def _seen_by(self, bf) -> bool:
        """Could a known enemy see us right now (their cone, our position)?"""
        me = bf.me.get("pos", (0.0, 0.0, 0.0))
        vrange = float(self.cfg.vision_range)
        near = float(self.cfg.near_range)
        half = math.radians(float(self.cfg.fov_deg)) * 0.5
        for t in bf.tracks.values():
            if t.kind != "mech" or t.dead or t.pos is None:
                continue
            d = dist3(me, t.pos)
            if d > vrange:
                continue
            if d <= near:
                return True
            if t.aim is None:
                continue
            brg = math.atan2(me[1] - t.pos[1], me[0] - t.pos[0])
            if abs(angle_diff(float(t.aim[0]), brg)) <= half:
                return True
        return False

    def _ttk_ok(self, bf, t, hp: float, d: float) -> bool:
        """Would we win this exchange at range d?"""
        p_us = pw.our_power(self.cfg, bf.me, d)
        if p_us <= 1e-6:
            return False
        hp_frac = t.hp_frac if t.hp_frac is not None else 0.75
        p_them = pw.power(self.cfg, hp_frac, int(t.cubes or 0),
                          t.weapons or ("gun",), d)
        if p_them <= 1e-6:
            return True
        their_hp = float(t.hp if t.hp is not None else self.cfg.max_hp)
        my_ttk = their_hp / p_us
        their_ttk = hp / p_them
        return their_ttk / max(1e-6, my_ttk) >= tuning.FIGHT_TTK_RATIO

    def _isolated(self, bf, t, d: float) -> bool:
        """No pack behind the target: its backup must be weaker than we are."""
        if t.pos is None:
            return False
        p_us = pw.our_power(self.cfg, bf.me, d)
        support = 0.0
        for o in bf.tracks.values():
            if o.id == t.id or o.kind != "mech" or o.dead or o.pos is None:
                continue
            dd = math.hypot(o.pos[0] - t.pos[0], o.pos[1] - t.pos[1])
            if dd > tuning.FIGHT_SUPPORT_M:
                continue
            hp_frac = o.hp_frac if o.hp_frac is not None else 0.75
            support += pw.power(self.cfg, hp_frac, int(o.cubes or 0),
                                o.weapons or ("gun",), dd)
        return support < tuning.FIGHT_SUPPORT_FRAC * p_us

    def _crate_aim(self, bf, pos):
        """Aim at a crate when it is in gun range with a clear shot."""
        me = bf.me
        my = me.get("pos", (0.0, 0.0, 0.0))
        d = math.hypot(pos[0] - my[0], pos[1] - my[1])
        if d < 4.0 or d > tuning.CRATE_RANGE_M:
            return None
        slots = me.get("weapons") or []
        w = slots[0] if slots else None
        if not w or not isinstance(w, dict):
            return None
        if float(w.get("cooldown", 0.0) or 0.0) > 0.0:
            return None
        if float(w.get("reload", 0.0) or 0.0) > 0.0:
            return None
        if w.get("ammo") is not None and int(w.get("ammo") or 0) <= 0:
            return None
        mh = float((me.get("stats") or {}).get("muzzle_height",
                                               self.cfg.muzzle_height))
        muzzle = (my[0], my[1], my[2] + mh)
        target = (pos[0], pos[1], pos[2] + 1.2)
        if self.los.shot(muzzle, target):
            return None
        dx, dy = target[0] - muzzle[0], target[1] - muzzle[1]
        return self.combat.face(bf, math.atan2(dy, dx))

    def _enemy_near(self, bf) -> bool:
        me = bf.me.get("pos", (0.0, 0.0, 0.0))
        for t in bf.tracks.values():
            if t.kind != "mech" or t.dead or t.pos is None:
                continue
            if dist3(me, t.pos) <= tuning.SILENT_RADIUS_M:
                return True
        return False

    def _cap_silent(self, bf, move):
        """Below sound.step_speed a mech makes no footstep; use it while walking
        to loot or to explore when anyone could be listening."""
        if abs(move[0]) + abs(move[1]) < 0.01 or not self._enemy_near(bf):
            return move
        cap = tuning.SILENT_SPEED_MPS / max(1.0, float(self.cfg.walk_speed))
        n = math.hypot(move[0], move[1])
        if n <= cap:
            return move
        return (move[0] / n * cap, move[1] / n * cap)

    def _laser_carrier(self, bf) -> bool:
        me = bf.me.get("pos", (0.0, 0.0, 0.0))
        for t in bf.tracks.values():
            if (t.kind != "mech" or t.dead or t.status != "visible"
                    or t.pos is None or "laser" not in (t.weapons or ())):
                continue
            if dist3(me, t.pos) < 280.0:
                return True
        return False

    def _lightning_close(self, bf) -> bool:
        """A visible lightning carrier inside its 45 m arc: get out of it."""
        me = bf.me.get("pos", (0.0, 0.0, 0.0))
        for t in bf.tracks.values():
            if (t.kind != "mech" or t.dead or t.status != "visible"
                    or t.pos is None or "lightning" not in (t.weapons or ())):
                continue
            if dist3(me, t.pos) < 55.0:
                return True
        return False

    def _laser_aimed(self, bf) -> bool:
        me = bf.me.get("pos", (0.0, 0.0, 0.0))
        for t in bf.tracks.values():
            if (t.kind != "mech" or not t.charging or t.pos is None
                    or t.aim is None or t.status != "visible"):
                continue
            brg = math.atan2(me[1] - t.pos[1], me[0] - t.pos[0])
            if abs(angle_diff(float(t.aim[0]), brg)) < TAU_LASER:
                return True
        return False

    def _duel_target(self, bf, hpf: float, slack: float, t=None):
        """A visible mech worth fighting, or None.

        Duel entry is deliberately conservative: healthy, zone margin > 15 s,
        target inside 170 m. The target itself is picked once by Combat so the
        aim solution and the movement loop use the same lock.
        """
        if t is None:
            t = self.combat.target(bf)
        if t is None or t.pos is None:
            return None
        if hpf < 0.6 or slack <= 15.0:
            return None
        me = bf.me.get("pos", (0.0, 0.0, 0.0))
        d = dist3(me, t.pos)
        if d > 170.0:
            return None
        # fight the mech that is shooting us, or a close one; do not chase
        # passives across the map and lose the rotation
        attacking = (t.last_damaged_us_t is not None
                     and bf.t - t.last_damaged_us_t < 3.0)
        if not attacking and d > 100.0:
            return None
        if not attacking and tuning.FIGHT_GATE_ENABLE:
            # only start fights we win, against a target with no pack behind it
            hp = float(bf.me.get("hp", self.cfg.max_hp))
            if not self._ttk_ok(bf, t, hp, d):
                return None
            if not self._isolated(bf, t, d):
                return None
        self.target = t
        self.target_seen = bf.t
        return t

    def _fight_move(self, bf, hpf: float, t=None, sol=None, tta: float = 1e9):
        me = bf.me
        pos = me.get("pos", (0.0, 0.0, 0.0))
        z = pos[2]
        if t is None:
            t = self.target
        if t is None or t.pos is None:
            return (0.0, 0.0), False, False, ""
        down = bool(sol is not None and sol.get("down"))
        dx, dy = t.pos[0] - pos[0], t.pos[1] - pos[1]
        d = math.hypot(dx, dy) or 1.0
        ux, uy = dx / d, dy / d
        # 3-5 s strafe reversals (the published +0.35 lever)
        if bf.t >= self.fight_strafe_until:
            if self.rng.random() < 0.8:
                self.fight_strafe = -self.fight_strafe
            self.fight_strafe_until = bf.t + 3.0 + self.rng.random() * 2.0
        sx, sy = -uy * self.fight_strafe, ux * self.fight_strafe
        dodge = (
            self._dodge_vec(bf) if tta <= tuning.DODGE_HORIZON_S else (0.0, 0.0)
        )

        kinds = [w.get("kind") for w in (me.get("weapons") or []) if w]
        pref = 85.0
        if "lightning" in kinds:
            pref = 28.0
        theirs = set(t.weapons or ())
        if "lightning" in kinds:
            pass
        elif "lightning" in theirs:
            pref = max(pref, 64.0)
        elif "mortar" in theirs:
            pref = max(pref, 80.0)

        # While the weapon is ready, only the *other* shooters are avoided:
        # seeing the target is the objective. While it reloads/cools, the
        # target joins the avoid set and a hidden cell is worth a detour.
        avoid = [
            (x["x"], x["y"], x["z"], x["dps"], x["w"])
            for x in self._threat_list if x["id"] != t.id
        ][:5]
        if down:
            t_dps = (25.0 if t.kind == "npc" else self._dps(t, d))
            avoid.append((t.pos[0], t.pos[1], t.pos[2], t_dps, 1.0))

        if t.kind == "npc":
            target_body = (t.pos[0], t.pos[1], t.pos[2] + 1.75)
            target_eye = (t.pos[0], t.pos[1], t.pos[2] + 3.5)
        else:
            target_body = (t.pos[0], t.pos[1], t.pos[2] + 4.5)
            target_eye = (t.pos[0], t.pos[1], t.pos[2] + 8.0)
        zc = bf.zone.get("center", (0.0, 0.0))
        zr = float(bf.zone.get("radius", 0.0))
        muzzle_z = float(
            (me.get("stats") or {}).get("muzzle_height", self.cfg.muzzle_height)
        )
        # Trees hide us from the target's eye but do not stop a beam; against a
        # laser carrier only real geometry (shot LOS) counts as cover.
        beam_target = "laser" in theirs

        hold_dir = (0.0, 0.0)
        if down and bf.t < self.fight_cover_until:
            hold_dir = self.fight_cover_dir

        best = None
        best_score = -1e9
        best_hidden = False
        for k in range(-1, 16):
            if k < 0:
                cx, cy = pos[0], pos[1]
                ddx = ddy = 0.0
            else:
                a = k * math.pi / 8.0
                ddx, ddy = math.cos(a), math.sin(a)
                cx, cy = pos[0] + ddx * 6.0, pos[1] + ddy * 6.0
            f = self.local.floor_at(cx, cy, z)
            if f is None or abs(f - z) > 2.75:
                continue
            if zr > 1.0 and math.hypot(cx - zc[0], cy - zc[1]) > max(0.0, zr - 2.0):
                continue
            d_t = math.hypot(t.pos[0] - cx, t.pos[1] - cy)
            los_ok = not self.los.shot((cx, cy, f + muzzle_z), target_body)
            hidden = False
            if down:
                if not los_ok:
                    hidden = True
                elif not beam_target:
                    hidden = self.los.sight(
                        target_eye, (cx, cy, f + 4.5)
                    )
            rear_bonus = 0.0
            if not down and t.kind == "mech" and t.aim is not None:
                tb = math.atan2(cy - t.pos[1], cx - t.pos[0])
                front = math.radians(self.cfg.front_arc_deg) * 0.5
                if abs(angle_diff(float(t.aim[0]), tb)) > front:
                    rear_bonus = tuning.ATTACK_REAR_BONUS
            dps, nvis = self.local.exposure_at(cx, cy, f, avoid)
            clr = self.local.clearance(cx, cy)
            hold = 0.0
            if down and hidden and hold_dir != (0.0, 0.0):
                if ddx * hold_dir[0] + ddy * hold_dir[1] > 0.9:
                    hold = tuning.ATTACK_COVER_HOLD_BONUS
            score = (
                -1.1 * abs(d_t - pref)
                + (tuning.ATTACK_LOS_BONUS if (los_ok and not down) else 0.0)
                + (tuning.ATTACK_COVER_BONUS if (down and hidden) else 0.0)
                + hold
                + rear_bonus
                - 25.0 * nvis
                - 0.12 * dps
                + 8.0 * (ddx * sx + ddy * sy)
                + tuning.ATTACK_DODGE_BONUS * (ddx * dodge[0] + ddy * dodge[1])
                - 2.0 * max(0, 4 - clr)
                - (8.0 if k < 0 else 0.0)          # do not stand still
            )
            if score > best_score:
                best_score, best, best_hidden = score, (ddx, ddy), hidden
        if best is None:
            return (0.0, 0.0), False, False, ""
        if down and best_hidden:
            self.fight_cover_dir = best
            self.fight_cover_until = bf.t + tuning.ATTACK_COVER_HOLD_S
        elif not down:
            self.fight_cover_dir = (0.0, 0.0)
            self.fight_cover_until = -1e9
        energy = float(me.get("energy", self.cfg.energy))
        boost = False
        if not down and ((d > pref + 40.0 and energy > 40.0) or (
            self._lightning_close(bf) and energy > 25.0
        )):
            boost = True
        return normalize2(best[0], best[1]), False, boost, "cov" if best_hidden else ""

    def _feasible(self, mode: int, bf) -> bool:
        if mode == DODGE:
            return False
        if mode == COVER:
            return self.cover_node >= 0
        if mode == LOOT:
            return self.loot_pick is not None
        if mode == DISENGAGE:
            return self.dis_goal is not None
        if mode == EXPLORE:
            return self.explore_goal is not None
        return True

    def _hold_goal(self, bf, pos) -> Tuple[float, float]:
        zone = bf.zone
        now = bf.t
        if self.hold_node >= 0 and now - self.hold_t < 2.0:
            k = self.hold_node
            if math.hypot(self.road.x[k] - pos[0], self.road.y[k] - pos[1]) > 2.0:
                return (self.road.x[k], self.road.y[k])
        c = zone.get("next_center", (0.0, 0.0))
        r = float(zone.get("next_radius", 0.0))
        radius = max(60.0, math.hypot(pos[0] - c[0], pos[1] - c[1]) + 40.0)
        cands = [
            k for k in self.road.near_nodes(pos[0], pos[1], radius)
            if self.road.comp[k] == self.road.main
        ]
        # prefer the inner half of the next disc: holding at its rim leaves a
        # 400 m trip when the following phase reveals a new centre
        for frac in (0.35, 0.6, 0.9):
            lim = max(20.0, frac * r)
            best, bs = None, -1.0
            for k in cands:
                if math.hypot(self.road.x[k] - c[0], self.road.y[k] - c[1]) > lim:
                    continue
                s = float(self.road.hold[k])
                if self.strength is not None:
                    dens = self.strength.count_at(self.road.x[k], self.road.y[k])
                    s -= tuning.HOLD_DENSITY_W * min(1.0, dens / 0.2)
                if s > bs:
                    bs, best = s, k
            if best is not None:
                self.hold_node = best
                self.hold_t = now
                return (self.road.x[best], self.road.y[best])
        return (c[0], c[1])
