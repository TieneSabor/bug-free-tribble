"""Baked table integrity."""
from __future__ import annotations

import unittest

from support import load_config  # noqa: E402

from mechbot.static import load  # noqa: E402


class TestStatic(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.st = load()

    def test_counts(self) -> None:
        st = self.st
        self.assertGreater(st.meta["nodes"], 1000)
        self.assertGreater(st.meta["edges"], 2000)
        n = st.meta["nodes"]
        for name, arr in st.nodes.items():
            self.assertEqual(len(arr), n, name)
        self.assertEqual(st.edges["off"][-1], len(st.edges["dst"]))
        self.assertEqual(len(st.alt), len(st.meta["landmarks"]))
        for row in st.alt:
            self.assertEqual(len(row), n)

    def test_grid(self) -> None:
        st = self.st
        self.assertEqual(len(st.occ["ground"]), st.meta["nx"] * st.meta["ny"])
        self.assertEqual(
            len(st.layers["standable"]), st.meta["nx2"] * st.meta["ny2"]
        )

    def test_main_component(self) -> None:
        st = self.st
        main = st.meta["main_comp"]
        comp = st.nodes["comp"]
        self.assertGreaterEqual(main, 0)
        self.assertGreater(sum(1 for c in comp if c == main), 100)

    def test_edge_kinds(self) -> None:
        kinds = set(self.st.edges["kind"])
        self.assertTrue(kinds <= {0, 1, 2, 3}, kinds)


if __name__ == "__main__":
    unittest.main()
