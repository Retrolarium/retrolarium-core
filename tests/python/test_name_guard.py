"""The name guard: Retrolarium carries no names or tables taken from games."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

import helpers  # noqa: F401
from retrolarium_core import name_guard
from retrolarium_core.name_guard import Guard, digest, words

ROOT = Path(__file__).resolve().parents[2]


def git_repository(files: dict[str, str]) -> tempfile.TemporaryDirectory:
    directory = tempfile.TemporaryDirectory()
    root = Path(directory.name)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    return directory


class WordTests(unittest.TestCase):
    def test_identifiers_split_into_words(self) -> None:
        self.assertEqual(["k", "final", "boss", "max", "lives", "2"], words("kFinalBoss MAX_LIVES2"))

    def test_a_phrase_matches_however_it_is_written(self) -> None:
        guard = Guard(frozenset({digest("final boss")}), 2)
        for line in ("the final boss", "kFinalBoss", "FINAL_BOSS = 1", "final-boss.png"):
            self.assertEqual(["final boss"], guard.matches(line), line)
        self.assertEqual([], guard.matches("the final round"))

    def test_a_name_is_caught_in_the_plural(self) -> None:
        guard = Guard(frozenset({digest("royal seal"), digest("pony"), digest("box")}), 2)
        self.assertEqual(["royal seals"], guard.matches("the eight Royal Seals"))
        self.assertEqual(["ponies"], guard.matches("kPonies"))
        self.assertEqual(["boxes"], guard.matches("boxes"))
        self.assertEqual([], guard.matches("the royal seas"))

    def test_a_name_is_caught_over_a_line_break(self) -> None:
        guard = Guard(frozenset({digest("royal seal")}), 2)
        text = "first line\nthe eight Royal\n# Seals hide\n"
        self.assertEqual([(2, "royal seals")], guard.matches_text(text))

    def test_a_title_is_not_a_name(self) -> None:
        # A title stays even when one of its words is guarded, across lines
        # and string literals too.
        guard = Guard(frozenset({digest("bros")}), 1)
        self.assertEqual([], guard.matches("Super Mario Bros. 2"))
        self.assertEqual(["bros"], guard.matches("the bros"))
        text = name_guard.strip_titles('''"the Super "
    "Mario Bros." disk''')
        self.assertEqual([], [m for line in text.splitlines() for m in guard.matches(line)])


class RepositoryTests(unittest.TestCase):
    def test_names_and_tables_are_found_in_a_tree(self) -> None:
        guard = Guard(frozenset({digest("final boss")}), 2)
        table = ", ".join(str(n) for n in range(30))
        with git_repository({"src/a.cpp": "int kFinalBoss = 1;\n",
                             "src/b.py": f"T = [{table}]\n",
                             "third_party/c.cpp": f"int t[] = {{{table}}};\n",
                             "src/c.py": "SHORT = (1, 2, 3)\n"}) as directory:
            root = Path(directory)
            self.assertEqual(["src/a.cpp:1: in-game name 'final boss'"],
                             [f.render() for f in name_guard.check_names(root, guard)])
            self.assertEqual(["src/b.py:1: literal table of 30 numbers"],
                             [f.render() for f in name_guard.check_tables(root)])
            (root / name_guard.TABLES_ALLOWLIST).write_bytes(b"src/b.py  # a test table\n")
            self.assertEqual([], name_guard.check_tables(root))

    def test_this_repository_carries_no_game_names(self) -> None:
        self.assertEqual([], [f.render() for f in name_guard.check_names(ROOT)])

    def test_this_repository_carries_no_game_tables(self) -> None:
        self.assertEqual([], [f.render() for f in name_guard.check_tables(ROOT)])


if __name__ == "__main__":
    unittest.main()
