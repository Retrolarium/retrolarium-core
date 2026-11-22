import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))

from retrolarium_core import formatting  # noqa: E402

_REAL_RUN = subprocess.run


def _repository(files: dict[str, bytes]) -> Path:
    directory = tempfile.mkdtemp()
    repo = Path(directory)
    for name, data in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_bytes(data)
    _REAL_RUN(["git", "init", "-q", str(repo)], check=True)
    _REAL_RUN(["git", "-C", str(repo), "add", "-A"], check=True)
    return repo


def _fake_ruff(command, *args, **kwargs):
    """ruff format on stdin: refuses a syntax error, spaces an assignment."""
    if command[0] != "ruff":
        return _REAL_RUN(command, *args, **kwargs)
    text = kwargs["input"].decode("utf-8")
    if "def (" in text:
        raise subprocess.CalledProcessError(2, command, output=b"", stderr=b"error: Failed to parse at 1:5")
    return subprocess.CompletedProcess(command, 0, stdout=text.replace("x=1", "x = 1").encode("utf-8"), stderr=b"")


class FilesForTests(unittest.TestCase):
    def test_third_party_trees_and_formatignore_paths_are_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            for name in (
                "a.py",
                "third_party/b.py",
                "tools/third_party/c.py",
                "archive/d.py",
                "games/e.md",
                "games/f.py",
                "config/records.json",
                "config/kept.json",
            ):
                (repo / name).parent.mkdir(parents=True, exist_ok=True)
                (repo / name).write_text("x = 1\n", encoding="utf-8")
            (repo / ".formatignore").write_text(
                "# frozen\narchive/\ngames/*.py\nconfig/records.json\n", encoding="utf-8"
            )
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)

            self.assertEqual(["a.py"], formatting.files_for(repo, ("*.py",)))
            self.assertEqual(["games/e.md"], formatting.files_for(repo, ("*.md",)))
            self.assertEqual(["config/kept.json"], formatting.files_for(repo, ("*.json",)))


class FormatterFailureTests(unittest.TestCase):
    def test_a_refused_or_undecodable_file_is_an_error_of_its_own(self) -> None:
        repo = _repository(
            {
                "good.py": b"x=1\n",
                "bad.py": b"def (:\n",
                "latin.py": b"x = '\xff'\n",
                "settings.toml": b"a = 1\n",
            }
        )
        self.addCleanup(shutil.rmtree, repo, True)
        which = lambda program: program if program == "ruff" else None  # noqa: E731
        with mock.patch.object(formatting.shutil, "which", which), mock.patch.object(subprocess, "run", _fake_ruff):
            found = {result.language: result for result in formatting.results(repo, check=True)}
        python = found["Python"]
        self.assertEqual(("good.py",), python.changed)
        self.assertIn("bad.py: error: Failed to parse", python.error)
        self.assertIn("latin.py: not UTF-8", python.error)
        # The languages after the failing one still ran.
        self.assertEqual("npm install -g @taplo/cli", found["TOML"].missing)


class ExcludedFormatterTests(unittest.TestCase):
    def test_excluded_powershell_never_probes_or_starts_the_interpreter(self) -> None:
        repo = _repository({"script.ps1": b"Write-Output test\n"})
        self.addCleanup(shutil.rmtree, repo, True)

        def which(program):
            if program.lower() in ("powershell", "pwsh"):
                self.fail("excluded PowerShell formatter probed the interpreter")
            return None

        with mock.patch.object(formatting.shutil, "which", which):
            self.assertEqual([], formatting.results(repo, check=True, exclude=("PowerShell",)))


class OperandTests(unittest.TestCase):
    def test_a_file_named_like_an_option_is_passed_as_a_file(self) -> None:
        calls = []

        def call(command, repo):
            calls.append(command)
            listed = "./-x.json\n" if "--list-different" in command else ""
            return subprocess.CompletedProcess(command, 1 if listed else 0, stdout=listed, stderr="")

        with mock.patch.object(formatting, "_call", call), mock.patch.object(formatting.shutil, "which", str):
            changed, errors = formatting._json(Path("."), ["-x.json", "a.json"], True, True)
            self.assertEqual((["-x.json"], []), (changed, errors))
            self.assertEqual(["./-x.json", "./a.json"], calls[0][-2:])
            calls.clear()
            formatting._shell(Path("."), ["-y.sh"], True, True)
            self.assertEqual("./-y.sh", calls[0][-1])


if __name__ == "__main__":
    unittest.main()
