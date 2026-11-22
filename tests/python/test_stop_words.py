"""Stop words: private words never reach a public repository."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import helpers  # noqa: F401
from retrolarium_core import hooks, stop_words
from retrolarium_core.stop_words import StopWords

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "python"

# Stand-ins for the real list, which lives outside every repository.
LIST = """\
# a comment
[en]
example_corp
[ru]
примерн
[allow]
ExampleCorp/public-tool
"""
WORDS = StopWords(("example_corp", "примерн"), ("ExampleCorp/public-tool",))
IDENTITY = {
    "GIT_AUTHOR_NAME": "A",
    "GIT_AUTHOR_EMAIL": "a@example.org",
    "GIT_COMMITTER_NAME": "A",
    "GIT_COMMITTER_EMAIL": "a@example.org",
}


def git(root: Path, *args: str, env: dict | None = None, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        input=stdin,
        env=dict(os.environ, **IDENTITY, **(env or {})),
    )


def repository(directory: str) -> Path:
    root = Path(directory) / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", IDENTITY["GIT_AUTHOR_NAME"])
    git(root, "config", "user.email", IDENTITY["GIT_AUTHOR_EMAIL"])
    return root


def standalone(root: Path) -> bool:
    """Whether root is the top of its own Git repository (a published
    clone), not a folder of a larger one."""
    result = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=root, capture_output=True, text=True)
    return result.returncode == 0 and Path(result.stdout.strip()).resolve() == root.resolve()


class MatchingTests(unittest.TestCase):
    def test_case_and_separators_do_not_matter(self) -> None:
        self.assertEqual(["example_corp"], WORDS.find("at D:\\Work\\EXAMPLE_CORP\\tools"))
        self.assertEqual(["examplecorp"], WORDS.find("myExampleCorpTool"))
        self.assertEqual(["example corp", "example-corp"], (WORDS.find("Example-Corp and example corp")))
        self.assertEqual([], WORDS.find("an example, corp"))

    def test_a_stem_finds_its_inflections_in_any_case(self) -> None:
        self.assertEqual(["примерная"[:7]], WORDS.find("ПРИМЕРНАЯ фирма"))
        self.assertEqual(["примерн"], WORDS.find("в Примерной"))

    def test_allowed_text_is_skipped(self) -> None:
        self.assertEqual([], WORDS.find("see github.com/examplecorp/Public-Tool"))
        self.assertEqual(["examplecorp"], WORDS.find("see github.com/ExampleCorp/other"))

    def test_bytes_in_utf16_and_cp1251_are_read(self) -> None:
        self.assertEqual(["example_corp"], WORDS.find_bytes("at example_corp".encode("utf-16")))
        self.assertEqual(["примерн"], WORDS.find_bytes("Примерная".encode("cp1251")))

    def test_ascii_inside_a_binary_is_read(self) -> None:
        # 0x98 has no cp1251 character: the blob decodes as none of the texts.
        blob = b"\x89PNG\x00\x98 C:/Users/Example_Corp/build/game.pdb \x98\x00"
        self.assertEqual(["example_corp"], WORDS.find_bytes(blob))


class ListTests(unittest.TestCase):
    def test_the_list_is_read_by_sections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / stop_words.LIST_NAME
            path.write_text(LIST, encoding="utf-8")
            words = StopWords.read(path)
            self.assertEqual(("example_corp", "примерн"), words.words)
            self.assertEqual(("ExampleCorp/public-tool",), words.allowed)
            path.write_text("[de]\nwort\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown section"):
                StopWords.read(path)

    def test_the_list_is_found_above_the_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ):
            os.environ.pop(stop_words.ENVIRONMENT, None)
            inner = Path(directory) / "a" / "b"
            inner.mkdir(parents=True)
            self.assertIsNone(stop_words.locate(inner))
            (Path(directory) / stop_words.LIST_NAME).write_text(LIST, encoding="utf-8")
            self.assertEqual((Path(directory) / stop_words.LIST_NAME).resolve(), stop_words.locate(inner))
            os.environ[stop_words.ENVIRONMENT] = str(Path(directory) / "missing")
            self.assertIsNone(stop_words.locate(inner))

    def test_without_a_list_the_check_says_it_did_not_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ):
            os.environ[stop_words.ENVIRONMENT] = str(Path(directory) / "missing")
            # On a developer's machine: a warning, and the check passes.
            result = subprocess.run(
                [sys.executable, "-m", "retrolarium_core.stop_words", "check", directory],
                capture_output=True,
                text=True,
                env=dict(os.environ, PYTHONPATH=str(CORE), CI=""),
            )
            self.assertEqual(0, result.returncode)
            self.assertIn(stop_words.NOT_PERFORMED, result.stderr)

    def test_without_a_list_ci_and_a_push_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ):
            os.environ[stop_words.ENVIRONMENT] = str(Path(directory) / "missing")
            root = repository(directory)
            cases = ((["check", str(root)], "1"), (["check", str(root)], "true"), (["push", "origin", str(root)], ""))
            for command, ci in cases:
                result = subprocess.run(
                    [sys.executable, "-m", "retrolarium_core.stop_words", *command],
                    capture_output=True,
                    text=True,
                    input="",
                    env=dict(os.environ, PYTHONPATH=str(CORE), CI=ci),
                )
                self.assertEqual(1, result.returncode, (command, ci, result.stderr))
                self.assertIn(stop_words.NOT_PERFORMED, result.stderr)


class RepositoryTests(unittest.TestCase):
    def test_a_tree_and_its_paths_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory)
            (root / "ok.txt").write_text("nothing here\n", encoding="utf-8")
            (root / "notes.md").write_text("built at D:/Example_Corp\n", encoding="utf-8")
            (root / "examplecorp").mkdir()
            (root / "examplecorp" / "a.txt").write_text("x\n", encoding="utf-8")
            self.assertEqual(
                ["notes.md: example_corp", "path examplecorp/a.txt: examplecorp"],
                sorted(stop_words.check_tree(root, WORDS)),
            )

    def test_staged_changes_message_and_identity_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory)
            (root / "a.txt").write_text("clean\n", encoding="utf-8")
            (root / "b.txt").write_text("from Example-Corp\n", encoding="utf-8")
            git(root, "add", "a.txt", "b.txt")
            (root / "b.txt").write_text("clean on disk, not in the index\n", encoding="utf-8")
            self.assertEqual(["b.txt: example-corp"], stop_words.check_staged(root, WORDS))
            message = Path(directory) / "message"
            message.write_text("Примерная правка\n# examplecorp in a comment\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"GIT_AUTHOR_EMAIL": "me@examplecorp.com"}):
                problems = stop_words.check_message(root, message, WORDS)
            self.assertEqual(["author_ident: examplecorp", "commit message: примерн"], sorted(problems))

    def test_the_history_and_a_push_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory)
            (root / "a.txt").write_text("old text from examplecorp\n", encoding="utf-8")
            git(root, "add", "a.txt")
            git(root, "commit", "-q", "-m", "first")
            first = git(root, "rev-parse", "HEAD").stdout.strip()
            (root / "a.txt").write_text("clean now\n", encoding="utf-8")
            git(root, "commit", "-q", "-am", "Примерная правка")
            second = git(root, "rev-parse", "HEAD").stdout.strip()
            problems, commits, blobs = stop_words.check_history(root, WORDS)
            self.assertEqual((2, 2, 2), (len(problems), commits, blobs))
            self.assertTrue(any(p.startswith("blob ") for p in problems))
            self.assertTrue(any(p.startswith("commit ") for p in problems))
            # A push of the second commit over the first sends only the second.
            line = f"refs/heads/main {second} refs/heads/main {first}\n"
            problems, commits, blobs = stop_words.check_push(root, "origin", line, WORDS)
            self.assertEqual((1, 1, 1), (len(problems), commits, blobs))
            zero = "0" * 40
            problems, commits, _ = stop_words.check_push(root, "origin", f"refs/heads/main {second} x {zero}\n", WORDS)
            self.assertEqual((2, 2), (len(problems), commits))

    @unittest.skipIf(os.name == "nt", "Windows file names cannot hold a line break")
    def test_a_path_with_a_line_break_does_not_hide_the_files_after_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory)
            (root / "a\nb.txt").write_text("clean\n", encoding="utf-8")
            (root / "z.txt").write_text("from examplecorp\n", encoding="utf-8")
            git(root, "add", ".")
            self.assertEqual(["z.txt: examplecorp"], stop_words.check_staged(root, WORDS))
            git(root, "commit", "-q", "-m", "two files")
            problems, _, blobs = stop_words.check_history(root, WORDS)
            self.assertEqual(2, blobs)
            self.assertTrue(any("z.txt" in problem for problem in problems), problems)

    def test_an_object_git_does_not_have_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory)
            with self.assertRaises(stop_words.GitObjectError):
                list(stop_words._batch(root, ["0" * 40]))

    def test_a_second_name_of_the_same_blob_is_checked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory)
            (root / "a.txt").write_text("same bytes\n", encoding="utf-8")
            (root / "examplecorp.txt").write_text("same bytes\n", encoding="utf-8")
            git(root, "add", ".")
            git(root, "commit", "-q", "-m", "two names")
            problems, _, _ = stop_words.check_history(root, WORDS)
            self.assertTrue(any("examplecorp.txt" in problem for problem in problems), problems)


class HookTests(unittest.TestCase):
    def test_hooks_refuse_a_stop_word_and_pass_clean_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory)
            (Path(directory) / stop_words.LIST_NAME).write_text(LIST, encoding="utf-8")
            env = {stop_words.ENVIRONMENT: str(Path(directory) / stop_words.LIST_NAME)}
            installed = hooks.install(root)
            self.assertEqual(sorted(hooks.HOOKS), sorted(path.name for path in installed))
            (root / "a.txt").write_text("examplecorp\n", encoding="utf-8")
            git(root, "add", "a.txt")
            refused = git(root, "commit", "-q", "-m", "staged", env=env)
            self.assertNotEqual(0, refused.returncode, refused.stderr)
            self.assertIn("a.txt: examplecorp", refused.stdout + refused.stderr)
            (root / "a.txt").write_text("clean\n", encoding="utf-8")
            git(root, "add", "a.txt")
            self.assertNotEqual(0, git(root, "commit", "-q", "-m", "ExampleCorp message", env=env).returncode)
            accepted = git(root, "commit", "-q", "-m", "clean", env=env)
            self.assertEqual(0, accepted.returncode, accepted.stderr)
            self.assertEqual(sorted(hooks.HOOKS), sorted(path.name for path in hooks.uninstall(root)))

    def test_a_foreign_hook_is_kept(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory)
            foreign = hooks.hooks_folder(root) / "pre-commit"
            foreign.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                hooks.install(root)
            self.assertEqual("#!/bin/sh\nexit 0\n", foreign.read_text(encoding="utf-8"))

    def test_make_targets_are_found(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual([], hooks.make_targets(root))
            (root / "Makefile").write_text("lint: x\n\nformat-check:\n\techo\n", encoding="utf-8")
            self.assertEqual(["lint", "format-check"], hooks.make_targets(root))

    @unittest.skipUnless(shutil.which("make"), "make runs the lint target")
    def test_the_installed_environment_reaches_make(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory)
            env = {stop_words.ENVIRONMENT: str(Path(directory) / "missing")}
            env["CI"] = ""  # a missing list only warns outside CI
            (root / "Makefile").write_text('lint:\n\t@test "$$HOOK_PROBE" = "it\'s set"\n', encoding="utf-8")
            git(root, "add", "Makefile")
            hooks.install(root)
            self.assertNotEqual(0, git(root, "commit", "-q", "-m", "without", env=env).returncode)
            hooks.install(root, environment={"HOOK_PROBE": "it's set"})
            accepted = git(root, "commit", "-q", "-m", "with", env=env)
            self.assertEqual(0, accepted.returncode, accepted.stderr)

    @unittest.skipUnless(shutil.which("sh"), "the hooks are sh scripts")
    def test_paths_and_values_in_a_hook_are_never_expanded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            gone = Path(directory) / "a b" / "$HOME `x`" / "python"
            with mock.patch.object(hooks.sys, "executable", str(gone)):
                text = hooks.script("pre-commit", {"PROBE": "$HOME 'q'"})
            hook = Path(directory) / "hook"
            hook.write_text(text, encoding="utf-8", newline="\n")
            result = subprocess.run(["sh", hook.as_posix()], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn(f"RETROLARIUM HOOKS NOT RUN: {gone.as_posix()} is gone", result.stderr)
            self.assertIn("export PROBE='$HOME '\\''q'\\'''", text)

    def test_an_environment_name_must_be_a_shell_variable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = repository(directory)
            with self.assertRaises(ValueError):
                hooks.install(root, environment={"A;rm -rf ~": "x"})
            self.assertFalse((hooks.hooks_folder(root) / "pre-commit").exists())
            for bad in ("NOVALUE", "A B=1", "=1"):
                with self.assertRaises(SystemExit) as raised, mock.patch("sys.stderr"):
                    hooks.main(["install", str(root), "--env", bad])
                self.assertEqual(2, raised.exception.code)


class ThisRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.words = stop_words.load(ROOT)
        if self.words is None:
            self.skipTest(stop_words.not_performed(ROOT))

    def test_this_tree_carries_no_stop_words(self) -> None:
        self.assertEqual([], stop_words.check_tree(ROOT, self.words))

    @unittest.skipUnless(standalone(ROOT), "the history is checked in a clone of this repository")
    def test_this_history_carries_no_stop_words(self) -> None:
        self.assertEqual([], stop_words.check_history(ROOT, self.words)[0])


if __name__ == "__main__":
    unittest.main()
