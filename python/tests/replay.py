#!/usr/bin/env python3
"""Replay check/stream.jsonl.gz through the bot and report latency/modes."""
from __future__ import annotations

import gzip
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PYDIR = os.path.dirname(HERE)
ROOT = os.path.dirname(PYDIR)
if PYDIR not in sys.path:
    sys.path.insert(0, PYDIR)

import bot as botmod  # noqa: E402


def main() -> int:
    path = os.path.join(ROOT, "check", "stream.jsonl.gz")
    if len(sys.argv) > 1:
        path = sys.argv[1]
    hello = None
    obs = []
    with gzip.open(path, "rt") as f:
        for line in f:
            m = json.loads(line)
            if m.get("type") == "hello":
                hello = m
            elif m.get("type") == "obs":
                obs.append(m)
    if hello is None:
        print("no hello in", path, file=sys.stderr)
        return 2
    hello.setdefault("map", {})["dir"] = os.path.join(ROOT, "arena")

    t0 = time.perf_counter()
    b = botmod.Bot(hello)
    load_ms = (time.perf_counter() - t0) * 1000.0
    times = []
    modes = {}
    errors = 0
    for o in obs:
        t = time.perf_counter()
        try:
            b.act(o)
        except Exception:
            errors += 1
        times.append((time.perf_counter() - t) * 1000.0)
        name = b.machine.current.name if b.machine.current else "none"
        modes[name] = modes.get(name, 0) + 1
    times.sort()

    def pct(p: float) -> float:
        return times[min(len(times) - 1, int(len(times) * p))]

    print("hello/map load: %.1f ms" % load_ms)
    print("observations: %d  errors: %d" % (len(times), errors))
    if times:
        print(
            "act ms: p50 %.2f  p90 %.2f  p99 %.2f  max %.2f"
            % (pct(0.50), pct(0.90), pct(0.99), times[-1])
        )
    print("modes:", " ".join("%s=%d" % (k, v) for k, v in sorted(modes.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
