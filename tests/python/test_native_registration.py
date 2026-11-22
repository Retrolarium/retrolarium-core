"""CTest and the portable runner must see the same real registrations."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which("cmake") and shutil.which("ctest"), "CMake and CTest are not installed")
class NativeRegistrationTests(unittest.TestCase):
    @unittest.skipIf(
        os.name != "nt" and not any(shutil.which(c) for c in ("c++", "g++", "clang++")),
        "no host C++ compiler",
    )
    def test_cli_enabled_and_disabled_register_the_same_tests_in_both_runners(self):
        with tempfile.TemporaryDirectory() as temporary:
            for cli in ("ON", "OFF"):
                with self.subTest(cli=cli):
                    build = Path(temporary) / cli
                    result = subprocess.run(
                        [
                            "cmake",
                            "-S",
                            str(ROOT),
                            "-B",
                            str(build),
                            "-DBUILD_TESTING=ON",
                            "-DRETROLARIUM_CORE_BUILD_TESTS=ON",
                            "-DRETROLARIUM_CORE_BUILD_CLI=" + cli,
                        ],
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    ctest = json.loads(
                        subprocess.check_output(
                            [
                                "ctest",
                                "--test-dir",
                                str(build),
                                "-C",
                                "Release",
                                "--show-only=json-v1",
                            ],
                            text=True,
                        )
                    )
                    manifest = json.loads((build / "tests.json").read_text(encoding="utf-8"))
                    self.assertEqual(
                        {item["name"] for item in ctest["tests"]},
                        {item["name"] for item in manifest},
                    )
                    self.assertEqual(7 if cli == "ON" else 2, len(manifest))
