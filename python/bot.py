#!/usr/bin/env python3
"""Baseline v2 entrypoint: baked map -> perception -> arbiter -> action.

Falls back to the v1 zone-only behaviour (with map-based LOS) if the baked
tables are missing or fail their hashes, so the bot always plays.
"""
from __future__ import annotations

import math
import os
import random
import time
import traceback
from typing import Any, Dict

import wire as mf

from mechbot import tuning
from mechbot.action.builder import ActionBuilder
from mechbot.config import Config
from mechbot.decision.arbiter import Arbiter
from mechbot.decision.combat import Combat
from mechbot.geometry import normalize2
from mechbot.perception.tracking import Perception
from mechbot.static import try_load
from mechbot.perception.strength import StrengthField
from mechbot.world.field import Field
from mechbot.world.localplan import LocalPlan
from mechbot.world.los import Los, MapLos
from mechbot.world.mapmodel import MapModel
from mechbot.world.roadmap import Roadmap


class Bot:
    name = "baseline-v2"

    def __init__(self, hello: Dict[str, Any]):
        self.cfg = Config(hello)
        self.builder = ActionBuilder(self.cfg)
        self.rng = random.Random(int(hello.get("seed", 0)))
        self.errors = 0

        st, err = try_load()
        self.static = st
        if st is None:
            self.mapmodel = MapModel(hello.get("map", {}), self.cfg)
            self.los = MapLos(self.mapmodel)
            self.perception = Perception(self.cfg, self.los)
            self.arbiter = None
            self.combat = Combat(self.cfg, self.los)
            mf.log("[v2] baked tables unavailable (%s); v1 fallback" % err)
            return

        self.mapmodel = None
        self.los = Los(st)
        self.perception = Perception(self.cfg, self.los)
        self.combat = Combat(self.cfg, self.los)
        self.road = Roadmap(st, self.los)
        self.field = Field(self.road, self._walk())
        self.local = LocalPlan(st, self.los, self.field, self._walk())
        self.strength = StrengthField(self.cfg, self.road, self._walk())
        self.arbiter = Arbiter(
            self.cfg, self.road, self.field, self.local, self.combat, self.los, self.rng,
            strength=self.strength,
        )
        mf.log(
            "[v2] bake %d nodes / %d edges, main comp %d, walk %.1f"
            % (st.meta["nodes"], st.meta["edges"] // 2, st.meta["main_comp"], self._walk())
        )

    def _walk(self) -> float:
        return max(1.0, float(self.cfg.walk_speed))

    # --- fallback -----------------------------------------------------
    def _fallback(self, bf) -> Dict[str, Any]:
        me = bf.me
        pos = me.get("pos", (0.0, 0.0, 0.0))
        z = bf.zone
        goal = z.get("next_center", (0.0, 0.0))
        ux, uy = normalize2(goal[0] - pos[0], goal[1] - pos[1])
        if math.hypot(goal[0] - pos[0], goal[1] - pos[1]) < 3.0:
            ux, uy = 0.0, 0.0
        ux, uy = ux * 0.38, uy * 0.38
        target = self.combat.target(bf)
        if target is not None:
            res = self.combat.aim_fire(bf, target)
            aim, fire, rel = res["aim"], res["fire"], res["reload"]
        else:
            aim = (math.atan2(uy, ux) if ux or uy else float(me.get("aim", (0.0, 0.0))[0]), 0.0)
            fire, rel = [False, False], False
        return dict(move=(ux, uy), aim=aim, fire=fire, reload=rel)

    # --- loop ---------------------------------------------------------
    def act(self, obs: Dict[str, Any]) -> Dict[str, Any]:
        try:
            _t0 = time.perf_counter()
            bf = self.perception.update(obs)
            _t1 = time.perf_counter()
            if self.arbiter is not None:
                intent = self.arbiter.decide(bf)
                _t2 = time.perf_counter()
                if os.environ.get("MECH_DEBUG") and (_t2 - _t0) > 0.015:
                    mf.log("[slow] t=%.1f perc=%.1fms decide=%.1fms label=%s"
                           % (bf.t, (_t1 - _t0) * 1e3, (_t2 - _t1) * 1e3, intent.label))
                if os.environ.get("MECH_DEBUG") and int(obs.get("tick", 0)) % 40 == 0:
                    me = bf.me
                    pos = me.get("pos", (0.0, 0.0, 0.0))
                    z = bf.zone
                    mf.log(
                        "[dbg] t=%.1f pos=(%.0f,%.0f,%.0f) in=%s r=%.0f nr=%.0f "
                        "hp=%.0f %s"
                        % (bf.t, pos[0], pos[1], pos[2], me.get("in_zone"),
                           float(z.get("radius", 0.0)),
                           float(z.get("next_radius", 0.0)),
                           float(me.get("hp", 0.0)), intent.label)
                    )
            else:
                fb = self._fallback(bf)
                from mechbot.action.intent import Intent
                intent = Intent(move=fb["move"], aim=fb["aim"], fire=fb["fire"],
                                reload=fb["reload"], label="fallback")
            return self.builder.build(intent, obs)
        except Exception:
            self.errors += 1
            if self.errors <= 5 or self.errors % 100 == 0:
                mf.log("act() failed (%d):\n%s" % (self.errors, traceback.format_exc()))
            return self.builder.fallback(obs)


if __name__ == "__main__":
    mf.run(Bot)
