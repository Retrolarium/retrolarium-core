"""CTest and the portable runner must see the same real registrations."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def compiler_unavailable(output: str) -> bool:
    return any(
        message in output
        for message in (
            "No CMAKE_CXX_COMPILER could be found",
            "could not find any instance of Visual Studio",
        )
    )


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
                    diagnostics = result.stdout + result.stderr
                    if result.returncode and compiler_unavailable(diagnostics):
                        self.skipTest("no working host C++ compiler: " + diagnostics[-1000:])
                    self.assertEqual(0, result.returncode, diagnostics)
                    subprocess.run(
                        ["cmake", "--build", str(build), "--config", "Release", "--parallel", "2"],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
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
                    by_name = {item["name"]: item for item in ctest["tests"]}
                    for item in manifest:
                        command = by_name[item["name"]]["command"]
                        expected_arguments = []
                        for argument in item["arguments"]:
                            if argument.startswith("repo:"):
                                argument = (ROOT / argument.removeprefix("repo:")).as_posix()
                            elif argument.startswith("bin:"):
                                argument = (build / argument.removeprefix("bin:")).as_posix()
                            expected_arguments.append(argument)
                        expected_exit = item["expected_exit"]
                        if expected_exit == 0:
                            self.assertEqual(expected_arguments, command[1:])
                            self.assertEqual(item["program"], Path(command[0]).name)
                        else:
                            definitions = dict(arg[2:].split("=", 1) for arg in command[1:] if arg.startswith("-D"))
                            self.assertEqual(expected_exit, int(definitions["EXPECTED"]))
                            self.assertEqual(expected_arguments, definitions["ARGUMENTS"].split("|"))
                            self.assertEqual(item["program"], Path(definitions["RLCORE"]).name)


class CompilerDiagnosticsTests(unittest.TestCase):
    def test_missing_windows_and_posix_compilers_are_distinguished_from_project_errors(self):
        self.assertTrue(compiler_unavailable("No CMAKE_CXX_COMPILER could be found"))
        self.assertTrue(compiler_unavailable("could not find any instance of Visual Studio"))
        self.assertFalse(compiler_unavailable("CMake Error: unknown source file"))
        self.assertFalse(compiler_unavailable("is not able to compile a simple test program: linker regression"))
