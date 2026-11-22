"""One version for retrolarium-core: the Python package, CMake and rlcore."""

from __future__ import annotations

from pathlib import Path
import re
import sys
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

import retrolarium_core  # noqa: E402
from retrolarium_core import tool as core_tool  # noqa: E402


def cmake_version() -> str:
    text = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
    found = re.search(r"project\(\s*RetrolariumCore\s+VERSION\s+([0-9.]+)", text)
    assert found, "CMakeLists.txt has no project(RetrolariumCore VERSION ...)"
    return found.group(1)


class VersionTests(unittest.TestCase):
    def test_pyproject_package_and_cmake_carry_one_version(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        self.assertEqual(pyproject, cmake_version())
        self.assertEqual(pyproject, retrolarium_core.__version__)
        self.assertEqual(pyproject, core_tool.RLCORE_VERSION)

    def test_rlcore_prints_the_generated_version(self) -> None:
        main = (ROOT / "cli" / "main.cpp").read_text(encoding="utf-8")
        self.assertIn("#include <retrolarium/core/version.hpp>", main)
        self.assertIsNone(re.search(r'"\d+\.\d+\.\d+"', main), "rlcore hard-codes a version")
        template = (ROOT / "cmake" / "version.hpp.in").read_text(encoding="utf-8")
        self.assertIn("@RetrolariumCore_VERSION@", template)


if __name__ == "__main__":
    unittest.main()
