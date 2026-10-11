"""Keep the names inside games out of Retrolarium's own repositories.

A game's characters, enemies, items and places belong to the game: its
repository keeps them in config/names.json, and Retrolarium reads them from
there when a project opens. This module checks that Retrolarium's
repositories (core, kit, studio, disassembler) do not carry them, in text,
comments or identifiers.

The guard is a list of SHA-256 digests (name_guard.sha256), one per name a
game repository marks as distinctive (its "guard" list), so the guard itself
names nothing. A file is read as words: runs of letters and digits, with
identifiers split at case changes and underscores (kFinalBoss reads as
"k final boss"); every run of up to `max_words` words is hashed and looked up.
Game titles stay in Retrolarium, so the words of a title are removed first
(a title may contain a character's name).

    python -m retrolarium_core.name_guard check [ROOT]
    python -m retrolarium_core.name_guard tables [ROOT]
    python -m retrolarium_core.name_guard update GAMES_DIR

`tables` reports literal runs of 24 numbers or more (a table copied from a
game would look like one) outside third_party trees, apart from the files the
repository's `name_guard_tables.txt` lists with the reason each one may hold
such a table (hardware tables, the kit's own layout description).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

GUARD_FILE = Path(__file__).with_name("name_guard.sha256")
TABLES_ALLOWLIST = "name_guard_tables.txt"

# Game titles Retrolarium names; matched without regard to case, and across
# spaces, line breaks, quotes, comment marks, dots, underscores or hyphens
# between their words (a title may run over two string literals or comment
# lines).
TITLES = ("super mario bros",)
_TITLE_RES = tuple(
    re.compile(r"[\s_.\-\"'#/*]*".join(title.split()), re.IGNORECASE) for title in TITLES
)


def strip_titles(text: str) -> str:
    """The text with every game title blanked, line breaks kept."""
    for title in _TITLE_RES:
        text = title.sub(lambda match: re.sub(r"[^\n]", " ", match.group(0)), text)
    return text


_CHUNK_RE = re.compile(r"[A-Za-z0-9]+")
_PART_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")
# A literal number in source or JSON: 0x1F, $1F, 31, 31.5.
_NUMBER = r"(?:0[xX][0-9A-Fa-f]+|\$[0-9A-Fa-f]+|-?[0-9]+(?:\.[0-9]+)?)[uUlL]*"
_NUMBER_RUN_RE = re.compile(rf"{_NUMBER}(?:\s*,\s*{_NUMBER})+")
TEXT_SUFFIXES = frozenset({
    ".c", ".cc", ".cpp", ".h", ".hpp", ".py", ".lua", ".js", ".ts", ".json", ".toml",
    ".md", ".txt", ".cmake", ".ps1", ".sh", ".yml", ".yaml", ".html", ".css", ".qml",
    ".ui", ".xml", ".cfg", ".ini", ".asm", ".inc", ".s", ".rlj", ".tsv",
})
TEXT_NAMES = frozenset({"CMakeLists.txt", "Makefile", "Dockerfile", ".gitignore", ".gitattributes"})
TABLE_SUFFIXES = frozenset({".c", ".cc", ".cpp", ".h", ".hpp", ".py", ".lua", ".js", ".json"})


def words(text: str) -> list[str]:
    """The lower-case words of a text, identifiers split into their parts."""
    result: list[str] = []
    for chunk in _CHUNK_RE.findall(text):
        result.extend(part.lower() for part in _PART_RE.findall(chunk))
    return result


def digest(phrase: str) -> str:
    return hashlib.sha256(" ".join(words(phrase)).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Guard:
    digests: frozenset[str]
    max_words: int

    @classmethod
    def load(cls, path: Path = GUARD_FILE) -> "Guard":
        digests: set[str] = set()
        max_words = 1
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("# max_words "):
                max_words = int(line.split()[-1])
            elif line and not line.startswith("#"):
                digests.add(line)
        return cls(frozenset(digests), max_words)

    def matches(self, line: str) -> list[str]:
        """The guarded phrases in a line, as the words that matched."""
        line = strip_titles(line)
        found: list[str] = []
        tokens = words(line)
        for start in range(len(tokens)):
            for length in range(1, self.max_words + 1):
                if start + length > len(tokens):
                    break
                phrase = " ".join(tokens[start : start + length])
                if hashlib.sha256(phrase.encode("utf-8")).hexdigest() in self.digests:
                    found.append(phrase)
        return found


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    detail: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.detail}"


def tracked_files(root: Path) -> list[str]:
    """The files Git tracks under root (relative, forward slashes)."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "."],
        cwd=root, capture_output=True, check=True,
    )
    return sorted(raw.decode("utf-8") for raw in listed.stdout.split(b"\0") if raw)


def _is_text(relative: str) -> bool:
    path = Path(relative)
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_NAMES


def _read(root: Path, relative: str) -> str | None:
    try:
        data = (root / relative).read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def check_names(root: Path, guard: Guard | None = None) -> list[Finding]:
    guard = guard or Guard.load()
    findings: list[Finding] = []
    for relative in tracked_files(root):
        if not _is_text(relative) or Path(relative).name == GUARD_FILE.name:
            continue
        text = _read(root, relative)
        if text is None:
            continue
        for number, line in enumerate(strip_titles(text).splitlines(), 1):
            for phrase in guard.matches(line):
                findings.append(Finding(relative, number, f"in-game name '{phrase}'"))
        for phrase in guard.matches(relative):
            findings.append(Finding(relative, 0, f"in-game name '{phrase}' in the path"))
    return findings


def table_allowlist(root: Path) -> set[str]:
    path = root / TABLES_ALLOWLIST
    if not path.is_file():
        return set()
    allowed: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            allowed.add(entry)
    return allowed


def check_tables(root: Path, minimum: int = 24) -> list[Finding]:
    """Literal runs of at least `minimum` numbers outside the allowlist."""
    allowed = table_allowlist(root)
    findings: list[Finding] = []
    for relative in tracked_files(root):
        if (Path(relative).suffix.lower() not in TABLE_SUFFIXES or relative in allowed
                or "third_party" in Path(relative).parts):
            continue
        text = _read(root, relative)
        if text is None:
            continue
        for match in _NUMBER_RUN_RE.finditer(text):
            count = match.group(0).count(",") + 1
            if count >= minimum:
                line = text.count("\n", 0, match.start()) + 1
                findings.append(Finding(relative, line, f"literal table of {count} numbers"))
    return findings


def update(games: Path, output: Path = GUARD_FILE) -> int:
    """Rewrite the guard from every game repository's config/names.json."""
    phrases: set[str] = set()
    for names in sorted(games.glob("*/config/names.json")):
        document = json.loads(names.read_text(encoding="utf-8"))
        phrases.update(" ".join(words(item)) for item in document.get("guard", []))
    phrases.discard("")
    max_words = max((len(phrase.split()) for phrase in phrases), default=1)
    lines = [
        "# SHA-256 of the names the game repositories guard (config/names.json),",
        "# written by python -m retrolarium_core.name_guard update GAMES_DIR.",
        f"# max_words {max_words}",
        *sorted(hashlib.sha256(phrase.encode("utf-8")).hexdigest() for phrase in phrases),
    ]
    output.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return len(phrases)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="name_guard", description=__doc__.split("\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "tables"):
        command = commands.add_parser(name)
        command.add_argument("root", nargs="?", type=Path, default=Path("."))
    refresh = commands.add_parser("update")
    refresh.add_argument("games", type=Path)
    args = parser.parse_args(argv)
    if args.command == "update":
        print(f"{update(args.games)} guarded names")
        return 0
    root = args.root.resolve()
    findings = check_names(root) if args.command == "check" else check_tables(root)
    for finding in findings:
        print(finding.render())
    what = "in-game names" if args.command == "check" else "literal tables"
    print(f"{len(findings)} {what} in {root.name}", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
