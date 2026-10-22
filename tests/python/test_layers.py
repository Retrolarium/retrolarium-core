"""retrolarium_core is the bottom layer: it imports neither the kit nor the
disassembler, which both build on it."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest

PACKAGE = Path(__file__).resolve().parents[2] / "python" / "retrolarium_core"


class LayerTests(unittest.TestCase):
    def test_core_imports_no_product_built_on_it(self) -> None:
        offenders = []
        for path in sorted(PACKAGE.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                elif isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                for name in names:
                    if name.split(".")[0] in ("retrolarium_kit", "retrolarium_disassembler"):
                        offenders.append(f"{path.relative_to(PACKAGE)}:{node.lineno} imports {name}")
        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()
