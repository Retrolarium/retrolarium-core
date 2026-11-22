"""Stable host names for bundled binaries."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))

from retrolarium_core.host import normalize_host  # noqa: E402


class HostTests(unittest.TestCase):
    def test_python_names_map_to_stable_identifiers(self) -> None:
        cases = {
            ("Windows", "AMD64"): "windows-x86_64",
            ("Linux", "x86_64"): "linux-x86_64",
            ("Linux", "aarch64"): "linux-aarch64",
            ("Darwin", "arm64"): "macos-aarch64",
            ("Windows", "x86"): "windows-x86",
            ("Linux", "i686"): "linux-x86",
            ("FreeBSD", "amd64"): "freebsd-x86_64",
        }
        for (system, machine), expected in cases.items():
            self.assertEqual(expected, normalize_host(system, machine), (system, machine))

    def test_unknown_names_pass_through_in_lower_case(self) -> None:
        self.assertEqual("haiku-riscv64", normalize_host("Haiku", "RISCV64"))

    def test_the_running_host_has_a_name(self) -> None:
        self.assertRegex(normalize_host(), r"^[a-z0-9_]+-[a-z0-9_]+$")


if __name__ == "__main__":
    unittest.main()
