"""Read-only access to the precompiled map tables.

Format: each `.bin` is zlib-compressed:
    magic u32 ("1VB2"), count u8, then per array: dtype code u8, size u32,
    adler32 u32, raw little-endian bytes.
"""
from __future__ import annotations

import json
import os
import struct
import zlib
from array import array
from typing import Dict, List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
CODES = {"B": 1, "h": 2, "H": 2, "i": 4, "f": 4}
DTYPE = {"u8": "B", "i16": "h", "u16": "H", "i32": "i", "f32": "f"}


class Static:
    __slots__ = ("meta", "layers", "occ", "nodes", "edges", "alt")

    def __init__(self, meta: dict, files: Dict[str, List[array]]):
        self.meta = meta
        self.layers: Dict[str, array] = dict(
            zip([n for n, _ in meta["fields"]["layers"]], files["layers"])
        )
        self.occ: Dict[str, array] = dict(
            zip([n for n, _ in meta["fields"]["occ"]], files["occ"])
        )
        self.nodes: Dict[str, array] = dict(
            zip([n for n, _ in meta["fields"]["nodes"]], files["nodes"])
        )
        self.edges: Dict[str, array] = dict(
            zip([n for n, _ in meta["fields"]["edges"]], files["edges"])
        )
        flat = files["alt"][0]
        n_lm = len(meta["landmarks"])
        nn = int(meta["nodes"])
        self.alt = [flat[r * nn : (r + 1) * nn] for r in range(n_lm)]

    # --- geometry -----------------------------------------------------
    @property
    def min_x(self) -> float:
        return float(self.meta["min_x"])

    @property
    def min_y(self) -> float:
        return float(self.meta["min_y"])

    @property
    def nx(self) -> int:
        return int(self.meta["nx"])

    @property
    def ny(self) -> int:
        return int(self.meta["ny"])

    @property
    def cell(self) -> float:
        return float(self.meta["grid_m"])

    def __repr__(self) -> str:
        return "<Static %d nodes, %d edges, %.1f MB>" % (
            self.meta["nodes"],
            self.meta["edges"] / 2,
            0.0,
        )


def _read(path: str) -> List[array]:
    with open(path, "rb") as f:
        payload = zlib.decompress(f.read())
    magic, count = struct.unpack_from("<IB", payload, 0)
    if magic != 0x32425631:
        raise ValueError("bad bake magic in %s" % path)
    off = 5
    out: List[array] = []
    for _ in range(count):
        code, size, adler = struct.unpack_from("<BII", payload, off)
        off += 9
        c = chr(code)
        itemsize = CODES[c]
        raw = payload[off : off + size * itemsize]
        if zlib.adler32(raw) & 0xFFFFFFFF != adler:
            raise ValueError("checksum mismatch in %s" % path)
        a = array(c)
        a.frombytes(raw)
        out.append(a)
        off += size * itemsize
    return out


def load(directory: str = HERE) -> Static:
    with open(os.path.join(directory, "meta.json"), "r", encoding="utf-8") as f:
        meta = json.load(f)
    files = {}
    for name in ("layers", "occ", "nodes", "edges", "alt"):
        files[name] = _read(os.path.join(directory, name + ".bin"))
    return Static(meta, files)


def try_load(directory: str = HERE) -> Tuple[Static, str]:
    try:
        return load(directory), ""
    except Exception as exc:  # noqa: BLE001 - fallback path must not raise
        return None, "%s: %s" % (type(exc).__name__, exc)
