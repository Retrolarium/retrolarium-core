"""The shared runner's actual subprocess behavior, on any host."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from retrolarium_core import testing


class PortableRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="runner with spaces-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.environment = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")

    def python_run(self) -> tuple[int, str]:
        # Keep deliberately failing child-suite output out of the parent
        # test report, while still running and checking the real subprocess.
        run = subprocess.run
        captured = []

        def capture(*args, **options):
            result = run(*args, **options, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            captured.append(result.stdout.decode("utf-8", errors="replace"))
            return result

        with patch.object(testing.subprocess, "run", side_effect=capture), redirect_stdout(io.StringIO()):
            code = testing.python_tests(self.root, "tests", self.environment)
        return code, "".join(captured)

    def test_python_discovery_runs_the_requested_checkout_and_propagates_failure(self) -> None:
        tests = self.root / "tests"
        tests.mkdir()
        source = tests / "test_probe.py"
        source.write_text(
            "import unittest\nclass Probe(unittest.TestCase):\n    def test_bad(self): self.fail('expected probe failure')\n",
            encoding="utf-8",
        )
        code, output = self.python_run()
        self.assertEqual(1, code)
        self.assertIn("expected probe failure", output)
        source.write_text(
            "import unittest\nclass Probe(unittest.TestCase):\n    def test_ok(self): self.assertTrue(True)\n",
            encoding="utf-8",
        )
        self.assertEqual(0, self.python_run()[0])

    def test_empty_python_discovery_is_a_failure(self) -> None:
        (self.root / "tests").mkdir()
        self.assertEqual(1, self.python_run()[0])

    def run_cases(self, cases: list[dict], timeout: float = 10) -> tuple[int, str]:
        manifest = self.root / "tests.json"
        manifest.write_text(json.dumps(cases), encoding="utf-8")
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            code = testing.native_tests(self.root, self.root, manifest, self.root / "games", self.environment, timeout)
        return code, output.getvalue()

    def case(self, name: str, script: str, **options) -> dict:
        path = self.root / f"{name} with spaces.py"
        path.write_text(script, encoding="utf-8")
        return {"name": name, "program": sys.executable, "arguments": [f"repo:{path.name}"], **options}

    def test_native_exit_codes_fixture_paths_and_skips_have_separate_results(self) -> None:
        success = self.case(
            "success", "import pathlib,sys\nassert pathlib.Path(sys.argv[1]).read_text() == 'fixture'\n"
        )
        (self.root / "input with spaces.txt").write_text("fixture", encoding="utf-8")
        success["arguments"].append("repo:input with spaces.txt")
        expected = self.case("expected", "raise SystemExit(3)\n", expected_exit=3)
        skip = self.case("skip", "raise SystemExit(77)\n")
        missing = {"name": "no game", "program": sys.executable, "arguments": ["games:missing.json"]}
        code, output = self.run_cases([success, expected, skip, missing])
        self.assertEqual(0, code)
        self.assertIn("2 passed, 2 skipped, 0 failed", output)

    def test_native_timeout_and_missing_program_are_failures(self) -> None:
        timeout = self.case("timeout", "import time\ntime.sleep(10)\n", expected_exit=1)
        missing = {"name": "absent", "program": "no-such-test", "arguments": ["games:missing.json"]}
        code, output = self.run_cases([timeout, missing], timeout=0.05)
        self.assertEqual(1, code)
        self.assertIn("0 passed, 0 skipped, 2 failed", output)

    def test_repository_fixture_is_required_and_never_silently_skipped(self) -> None:
        code, output = self.run_cases(
            [{"name": "bad fixture", "program": sys.executable, "arguments": ["repo:missing.py"]}]
        )
        self.assertEqual(1, code)
        self.assertIn("0 skipped, 1 failed", output)

    def test_a_ci_stopword_list_is_temporary_and_never_a_shell_argument(self) -> None:
        with patch.dict(os.environ, {"STOPWORDS_LIST": "[en]\nexample\n"}):
            os.environ.pop("RETROLARIUM_STOPWORDS", None)
            with testing.stopword_environment():
                path = Path(os.environ["RETROLARIUM_STOPWORDS"])
                self.assertEqual("[en]\nexample\n\n", path.read_text(encoding="utf-8"))
            self.assertNotIn("RETROLARIUM_STOPWORDS", os.environ)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
