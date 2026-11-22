"""Shared, shell-free test entrypoint for the four Retrolarium checkouts.

Python drives unittest, CMake and native test programs on every host. Native
programs remain native: tests.json records their names, fixtures and expected
exit codes. A missing game fixture or exit 77 is a skip; a missing program,
unexpected exit or timeout is a failure.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


CORE_PYTHON = Path(__file__).resolve().parents[1]


def _command(command: list[str], *, root: Path, environment: dict[str, str], timeout: float = 1800) -> int:
    print("+ " + " ".join(command), flush=True)
    try:
        return subprocess.run(command, cwd=root, env=environment, timeout=timeout, check=False).returncode
    except subprocess.TimeoutExpired:
        print(f"FAIL: command exceeded {timeout:g} seconds", file=sys.stderr)
    except OSError as error:
        print(f"FAIL: cannot start {command[0]}: {error}", file=sys.stderr)
    return -1


def python_tests(
    root: Path, start: str, environment: dict[str, str], pattern: str = "test*.py", match: str = ""
) -> int:
    # -I ignores installed user packages and ambient PYTHONPATH. The worker
    # explicitly selects these checkouts, including the exact Core running it.
    return _command(
        [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--worker", str(root), start, pattern, match],
        root=root,
        environment=environment,
    )


def _python_worker(arguments: list[str]) -> int:
    root, start, pattern, match = arguments
    repository = Path(root)
    sys.path[:0] = [str(repository / "tests"), str(repository / "src"), str(CORE_PYTHON)]
    os.chdir(repository)
    loader = unittest.TestLoader()
    if match:
        loader.testNamePatterns = [f"*{match}*"]
    suite = loader.discover(str(repository / start), pattern=pattern)
    if suite.countTestCases() == 0:
        print("FAIL: no Python tests discovered", file=sys.stderr)
        return 1
    return 0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1


def game_sources(root: Path, given: Path | None, environment: dict[str, str]) -> Path:
    if given is not None:
        return given.resolve()
    if environment.get("RETROLARIUM_GAME_SOURCES"):
        return Path(environment["RETROLARIUM_GAME_SOURCES"]).expanduser().resolve()
    for parent in root.parents:
        candidate = parent / "retrolariumlab"
        if candidate.is_dir():
            return candidate
    return root / "game-repositories-not-found"


def native_tests(
    root: Path,
    binary: Path,
    manifest: Path,
    games: Path,
    environment: dict[str, str],
    timeout: float,
    *,
    legacy_paths: bool = False,
) -> int:
    try:
        cases = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(cases, list) or not cases:
            raise ValueError("the manifest must be a nonempty list")
    except (OSError, ValueError) as error:
        print(f"FAIL: cannot read native tests from {manifest}: {error}", file=sys.stderr)
        return 1
    passed = skipped = failed = 0
    for case in cases:
        try:
            name, program = case["name"], binary / case["program"]
            if not isinstance(name, str) or not isinstance(case["arguments"], list):
                raise ValueError("invalid name or arguments")
            expected = case.get("expected_exit", 0)
            if not isinstance(expected, int) or not 0 <= expected <= 255:
                raise ValueError("expected_exit must be an integer from 0 to 255")
            arguments = []
            missing = []
            for item in case["arguments"]:
                if not isinstance(item, str):
                    raise ValueError("arguments must be strings")
                if item.startswith("games:"):
                    fixture = games / item.removeprefix("games:")
                    if not fixture.exists():
                        missing.append(fixture)
                    arguments.append(str(fixture))
                elif item.startswith("repo:"):
                    fixture = root / item.removeprefix("repo:")
                    if not fixture.exists():
                        raise ValueError(f"missing repository fixture: {fixture}")
                    arguments.append(str(fixture))
                elif item.startswith("bin:"):
                    arguments.append(str(binary / item.removeprefix("bin:")))
                elif legacy_paths:
                    # Compatibility with existing installed Studio manifests.
                    arguments.append(str(root / item))
                else:
                    arguments.append(item)
            print(f"== {name}", flush=True)
            if not program.is_file():
                raise ValueError(f"missing test program: {program}")
            if missing:
                print(f"SKIP: no game fixture {missing[0]}", flush=True)
                skipped += 1
                continue
            code = _command([str(program), *arguments], root=root, environment=environment, timeout=timeout)
            if code == 77:
                print("SKIP: test returned 77", flush=True)
                skipped += 1
            elif code == expected:
                passed += 1
            else:
                print(f"FAIL: {name}: exit {code}, expected {expected}", file=sys.stderr)
                failed += 1
        except (KeyError, TypeError, ValueError) as error:
            print(f"FAIL: invalid native test: {error}", file=sys.stderr)
            failed += 1
    print(f"Native tests: {passed} passed, {skipped} skipped, {failed} failed", flush=True)
    return int(failed != 0)


def _native(root: Path, kind: str, args: argparse.Namespace, environment: dict[str, str]) -> int:
    if args.bin is not None:
        binary = args.bin.resolve()
        manifest = binary / "tests.json"
    else:
        build = (args.build_dir or root / "build/tests").resolve()
        configure = ["cmake", "-S", str(root), "-B", str(build), f"-DCMAKE_BUILD_TYPE={args.config}"]
        if kind == "core":
            configure.extend(
                ["-DBUILD_TESTING=ON", "-DRETROLARIUM_CORE_BUILD_TESTS=ON", "-DRETROLARIUM_CORE_BUILD_CLI=ON"]
            )
        if args.sanitize:
            configure.append("-DRETROLARIUM_SANITIZE=ON")
        if args.qt_prefix is not None:
            configure.append(f"-DCMAKE_PREFIX_PATH={args.qt_prefix.resolve()}")
        configure.extend(args.cmake_arg)
        for command in (
            configure,
            ["cmake", "--build", str(build), "--config", args.config, "--parallel", str(args.jobs)],
        ):
            code = _command(command, root=root, environment=environment)
            if code:
                return code
        if kind == "studio":
            binary = build / "test-bin"
            code = _command(
                ["cmake", "--install", str(build), "--config", args.config, "--prefix", str(binary)],
                root=root,
                environment=environment,
            )
            if code:
                return code
            manifest = binary / "tests.json"
        else:
            binary = build / args.config if (build / args.config).is_dir() else build
            manifest = build / "tests.json"
    games = game_sources(root, args.game_sources, environment)
    code = native_tests(root, binary, manifest, games, environment, args.timeout, legacy_paths=kind == "studio")
    if kind == "core" and code == 0:
        tool = binary / ("rlcore.exe" if os.name == "nt" else "rlcore")
        if not tool.is_file():
            print(f"FAIL: Python bridge needs {tool}", file=sys.stderr)
            return 1
        environment["RETROLARIUM_CORE"] = str(tool)
        # This class contains only real codec round trips. With the explicit
        # tool they run, rather than silently skipping because PATH lacks it.
        if args.suite == "native":
            code = python_tests(root, "tests/python", environment, "test_core_tool.py", "CoreToolRoundTripTest")
    return code


@contextmanager
def stopword_environment():
    # CI supplies the private list as an environment value, never as shell
    # source or a command-line argument. Keep the temporary file private.
    secret = os.environ.get("STOPWORDS_LIST", "")
    if not secret or os.environ.get("RETROLARIUM_STOPWORDS"):
        yield
        return
    with tempfile.TemporaryDirectory(prefix="retrolarium-checks-") as folder:
        path = Path(folder) / "stopwords"
        path.write_text(secret + "\n", encoding="utf-8", newline="\n")
        os.environ["RETROLARIUM_STOPWORDS"] = str(path)
        try:
            yield
        finally:
            os.environ.pop("RETROLARIUM_STOPWORDS", None)


def checks(root: Path, names: bool, history: bool, formatting: bool) -> int:
    from retrolarium_core import formatting as formatter, name_guard, stop_words

    failed = False
    if formatting:
        print("SKIP: PowerShell formatting is outside the Python test runner", flush=True)
        failed |= formatter.run(root, check=True, exclude=("PowerShell",)) != 0
    if names:
        for operation in ("check", "tables"):
            failed |= name_guard.main([operation, str(root)]) != 0
    with stopword_environment():
        if stop_words.load(root) is None:
            if os.environ.get("RETROLARIUM_STOPWORDS") or os.environ.get("STOPWORDS_LIST"):
                print(f"FAIL: {stop_words.not_performed(root)}", file=sys.stderr)
                failed = True
            else:
                print(f"SKIP: {stop_words.not_performed(root)}", flush=True)
        else:
            for operation in ("check", "history") if history else ("check",):
                failed |= stop_words.main([operation, str(root)]) != 0
    return int(failed)


def main(root: Path, *, start: str = "tests", native: str | None = None, names: bool = False) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("all", "python", "native", "checks"), default="all")
    parser.add_argument("--bin", type=Path, help="run an existing installed native test suite without building")
    parser.add_argument("--build-dir", type=Path, help="CMake build directory (default: build/tests)")
    parser.add_argument("--config", default="Release")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=300, help="seconds per native test")
    parser.add_argument("--game-sources", type=Path)
    parser.add_argument("--qt-prefix", type=Path, help="Qt installation for a native Studio build")
    parser.add_argument("--cmake-arg", action="append", default=[], help="extra CMake argument; use --cmake-arg=-D...")
    parser.add_argument("--sanitize", action="store_true", help="Core ASan/UBSan with GCC or Clang")
    parser.add_argument("--checks", action="store_true", help="also run repository guards")
    parser.add_argument("--history", action="store_true", help="include historical objects in repository guards")
    parser.add_argument("--format", action="store_true", help="also check formatting")
    args = parser.parse_args()
    if args.jobs < 1 or args.timeout <= 0:
        parser.error("jobs and timeout must be positive")
    if args.bin is not None and (native is None or args.suite not in ("all", "native")):
        parser.error("--bin requires a native suite")
    if args.suite == "native" and native is None:
        parser.error("this repository has no native test suite")
    if args.sanitize and native != "core":
        parser.error("--sanitize is available only for Core")
    if args.bin is not None and (args.build_dir is not None or args.sanitize or args.cmake_arg):
        parser.error("--bin runs existing binaries; it cannot be combined with build options")
    root = root.resolve()
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    if args.qt_prefix is not None:
        environment["PATH"] = str(args.qt_prefix.resolve() / "bin") + os.pathsep + environment.get("PATH", "")
        environment["QT_PLUGIN_PATH"] = (
            str(args.qt_prefix.resolve() / "plugins") + os.pathsep + environment.get("QT_PLUGIN_PATH", "")
        )
    if args.game_sources is not None:
        environment["RETROLARIUM_GAME_SOURCES"] = str(args.game_sources.resolve())
    if (
        native == "studio"
        and sys.platform == "linux"
        and not (environment.get("DISPLAY") or environment.get("WAYLAND_DISPLAY"))
    ):
        environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    failed = False
    if args.suite in ("all", "native") and native is not None:
        failed |= _native(root, native, args, environment) != 0
    if args.suite in ("all", "python"):
        failed |= python_tests(root, start, environment) != 0
    if args.suite == "checks" or args.checks or args.history or args.format:
        failed |= checks(root, names, args.history, args.format) != 0
    return int(failed)


if __name__ == "__main__":
    if sys.argv[1:2] != ["--worker"] or len(sys.argv) != 6:
        raise SystemExit("Run the repository's tools/test.py entrypoint.")
    raise SystemExit(_python_worker(sys.argv[2:]))
