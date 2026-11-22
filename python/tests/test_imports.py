"""Enforce the package dependency DAG by parsing imports."""
from __future__ import annotations

import ast
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PYDIR = os.path.dirname(HERE)
PKG = os.path.join(PYDIR, "mechbot")

ROOT = {"mechbot.config", "mechbot.tuning", "mechbot.geometry", "mechbot.power"}


def _module_name(path: str) -> str:
    rel = os.path.relpath(path, PYDIR).replace(os.sep, ".")
    return rel[:-3] if rel.endswith(".py") else rel


def _imports(path: str):
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), path)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.append(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue
            mod = node.module
            if mod == "mechbot":
                for a in node.names:
                    out.append("mechbot." + a.name)
            else:
                out.append(mod)
    return out


def _allowed(importer: str, target: str) -> bool:
    if not target.startswith("mechbot."):
        return True
    if target == "mechbot.bot":
        return False
    if importer in ROOT:
        return target in ROOT
    if importer.startswith("mechbot.world."):
        return target in ROOT or target.startswith("mechbot.world")
    if importer.startswith("mechbot.perception."):
        return (
            target in ROOT
            or target == "mechbot.world.mapmodel"
            or target == "mechbot.world.los"
            or target.startswith("mechbot.perception")
        )
    if importer.startswith("mechbot.decision."):
        return (
            target in ROOT
            or target.startswith("mechbot.world")
            or target == "mechbot.perception.battlefield"
            or target == "mechbot.perception.items"   # read-only loot view
            or target == "mechbot.action.intent"
            or target.startswith("mechbot.decision")
        )
    if importer.startswith("mechbot.action."):
        return target in ROOT or target.startswith("mechbot.action")
    return target.startswith("mechbot." + importer.split(".")[1])


class TestImportDAG(unittest.TestCase):
    def test_dag(self) -> None:
        failures = []
        for root, _, files in os.walk(PKG):
            for name in files:
                if not name.endswith(".py") or name == "__init__.py":
                    continue
                path = os.path.join(root, name)
                importer = _module_name(path)
                for target in _imports(path):
                    if not _allowed(importer, target):
                        failures.append("%s imports %s" % (importer, target))
        self.assertEqual(failures, [], "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
