"""Keep private words out of Retrolarium's public repositories.

Some words must never reach a public repository: the owner's private folders,
employers, identities and internal project names. They are listed outside
every repository, in a `.stopwords` file that Git ignores: the first one found
in the repository's folder or a folder above it, or the file the
RETROLARIUM_STOPWORDS variable names. Lines starting with `#` are comments:

    [en]
    some_name
    [ru]
    имя
    [allow]
    a longer text in which a stop word is fine

Matching ignores case, Latin and Cyrillic alike. Inside a word, `_`, `-` and a
space each match any one of them or nothing, so `some_name` also finds
`Some-Name` and `SomeName`; a stem finds its inflected forms. Text matching an
`[allow]` line is skipped. File contents are read as UTF-8, UTF-16 and CP1251.

Without a list nothing is checked, and every command says so in capitals. On
a developer's machine that is a warning and the command succeeds; when the
`CI` variable is set (to anything but empty, 0 or false) and for `push`, which
the pre-push hook runs, it is an error: a check that cannot run must not pass
what it never read.

    python -m retrolarium_core.stop_words check [ROOT]
    python -m retrolarium_core.stop_words staged [REPO]
    python -m retrolarium_core.stop_words message FILE [REPO]
    python -m retrolarium_core.stop_words history [REPO] [--all]
    python -m retrolarium_core.stop_words push REMOTE [REPO] < refs
    python -m retrolarium_core.stop_words where [ROOT]

`check` reads the files Git tracks under ROOT (and the untracked ones it does
not ignore), their contents and paths. `staged` reads what the next commit
holds, `message` a commit message with the author and committer identities.
`history` reads everything reachable from the branches and tags (--all: every
ref): commit and tag messages, identities, paths and blob contents. `push`
reads the same for what a push sends (the pre-push hook's standard input).
`where` names the list in use. retrolarium_core.hooks runs them from Git.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from functools import lru_cache
import os
from pathlib import Path
import re
import subprocess
import sys
import threading

LIST_NAME = ".stopwords"
ENVIRONMENT = "RETROLARIUM_STOPWORDS"
SECTIONS = ("en", "ru", "allow")
NOT_PERFORMED = "STOP-WORD CHECK NOT PERFORMED"
_SEPARATORS = "_- "
_ZERO = "0" * 40


class GitObjectError(RuntimeError):
    """git could not hand over an object the check has to read."""


@dataclass(frozen=True)
class StopWords:
    words: tuple[str, ...]
    allowed: tuple[str, ...] = ()
    source: Path | None = None
    _pattern: re.Pattern | None = field(default=None, compare=False, repr=False)
    _allow: re.Pattern | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.words:
            object.__setattr__(
                self, "_pattern", re.compile("|".join(_word_pattern(word) for word in self.words), re.IGNORECASE)
            )
        if self.allowed:
            object.__setattr__(
                self, "_allow", re.compile("|".join(re.escape(text) for text in self.allowed), re.IGNORECASE)
            )

    @classmethod
    def read(cls, path: Path) -> "StopWords":
        lists: dict[str, list[str]] = {name: [] for name in SECTIONS}
        section = None
        for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip().lower()
                if section not in lists:
                    raise ValueError(f"{path}:{number}: unknown section [{section}]")
            elif section is None:
                raise ValueError(f"{path}:{number}: a word before the first section")
            else:
                lists[section].append(line)
        return cls(tuple(lists["en"] + lists["ru"]), tuple(lists["allow"]), path)

    def find(self, text: str) -> list[str]:
        """The stop words in a text, as written there (lower case)."""
        if self._pattern is None:
            return []
        if self._allow is not None:
            text = self._allow.sub(lambda match: " " * len(match.group()), text)
        return sorted({match.group().lower() for match in self._pattern.finditer(text)})

    def find_bytes(self, data: bytes) -> list[str]:
        found: set[str] = set()
        for encoding in ("utf-8", "utf-16", "cp1251"):
            try:
                text = data.decode(encoding)
            except UnicodeDecodeError:
                continue
            found.update(self.find(text))
        # A binary (an executable with a path in it, an image's metadata)
        # decodes as none of those; byte for byte it still shows its ASCII.
        found.update(self.find(data.decode("latin-1")))
        return sorted(found)


def _word_pattern(word: str) -> str:
    parts = re.split(f"[{re.escape(_SEPARATORS)}]+", word.strip())
    return f"[{re.escape(_SEPARATORS)}]?".join(re.escape(part) for part in parts if part)


def locate(start: Path) -> Path | None:
    """The stop-word list for a folder: RETROLARIUM_STOPWORDS, or the first
    .stopwords in the folder or above it."""
    named = os.environ.get(ENVIRONMENT)
    if named:
        return Path(named) if Path(named).is_file() else None
    for folder in [start.resolve(), *start.resolve().parents]:
        candidate = folder / LIST_NAME
        if candidate.is_file():
            return candidate
    return None


def load(start: Path) -> StopWords | None:
    path = locate(start)
    return StopWords.read(path) if path else None


def not_performed(start: Path) -> str:
    named = os.environ.get(ENVIRONMENT)
    where = f"{ENVIRONMENT}={named} is not a file" if named else f"no {LIST_NAME} in {start.resolve()} or above it"
    return f"{NOT_PERFORMED}: {where}"


def required(command: str) -> bool:
    """Whether a missing list fails the command: in CI, and for what a push
    sends."""
    return command == "push" or os.environ.get("CI", "").strip().lower() not in ("", "0", "false")


def _git(repo: Path, *args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], input=data or b"", capture_output=True, check=True).stdout


@lru_cache(maxsize=None)
def _git_version() -> tuple[int, int]:
    found = re.search(rb"(\d+)\.(\d+)", subprocess.run(["git", "version"], capture_output=True).stdout)
    return (int(found.group(1)), int(found.group(2))) if found else (0, 0)


def _read_until(stream, delimiter: bytes) -> bytes:
    line = bytearray()
    while True:
        byte = stream.read(1)
        if not byte or byte == delimiter:
            return bytes(line)
        line += byte


def _batch(repo: Path, names: list[str]):
    """(name, kind, body) for each object name, through git cat-file, one
    object in memory at a time. Names and answers are NUL-separated (git 2.42's
    -Z), so a path with a line break cannot shift the answers; an older git
    refuses such a path. An object git does not have, or a name it finds
    ambiguous, is a GitObjectError: nothing is skipped unread."""
    if not names:
        return
    separated = _git_version() >= (2, 42)
    if not separated:
        for name in names:
            if "\n" in name:
                raise GitObjectError(f"{name!r} has a line break, which git before 2.42 cannot check")
    separator = b"\0" if separated else b"\n"
    process = subprocess.Popen(
        ["git", "-C", str(repo), "cat-file", "--batch", *(["-Z"] if separated else [])],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )

    def feed() -> None:
        try:
            process.stdin.write(b"".join(name.encode("utf-8", "surrogateescape") + separator for name in names))
        except OSError:
            pass
        finally:
            process.stdin.close()

    # Written from a thread: git answers while it reads, and a full pipe
    # either way would stop both.
    writer = threading.Thread(target=feed, daemon=True)
    writer.start()
    try:
        for name in names:
            header = _read_until(process.stdout, separator).decode("utf-8", "surrogateescape")
            if not header:
                raise GitObjectError(f"git cat-file stopped before {name!r}")
            if header.endswith(" missing"):
                raise GitObjectError(f"git has no object {name!r}")
            if header.endswith(" ambiguous"):
                raise GitObjectError(f"the object name {name!r} is ambiguous")
            _sha, kind, size = header.split()
            body = process.stdout.read(int(size))
            process.stdout.read(1)
            yield name, kind, body
    finally:
        process.stdout.close()
        writer.join()
        process.wait()


def _tree_names(body: bytes) -> list[tuple[str, str]]:
    """(name, object) of each entry of a tree object."""
    entries = []
    position = 0
    while position < len(body):
        space = body.index(b" ", position)
        nul = body.index(b"\0", space)
        entries.append((body[space + 1 : nul].decode("utf-8", "surrogateescape"), body[nul + 1 : nul + 21].hex()))
        position = nul + 21
    return entries


def check_tree(root: Path, words: StopWords) -> list[str]:
    """Problems in the files Git tracks under root, their contents and paths."""
    listed = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", ".")
    problems = []
    for raw in listed.split(b"\0"):
        if not raw:
            continue
        relative = raw.decode("utf-8", "surrogateescape")
        found = words.find(relative)
        if found:
            problems.append(f"path {relative}: {', '.join(found)}")
        try:
            data = (root / relative).read_bytes()
        except OSError:
            continue
        found = words.find_bytes(data)
        if found:
            problems.append(f"{relative}: {', '.join(found)}")
    return problems


def check_staged(repo: Path, words: StopWords) -> list[str]:
    """Problems in what the next commit holds: the added and changed files,
    their staged contents and their paths."""
    listed = _git(repo, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR", "--no-renames")
    paths = [raw.decode("utf-8", "surrogateescape") for raw in listed.split(b"\0") if raw]
    problems = []
    for path in paths:
        found = words.find(path)
        if found:
            problems.append(f"path {path}: {', '.join(found)}")
    # A submodule's commit lives in the submodule, not here: its path is
    # checked, there is no content to read.
    submodules = set()
    for entry in _git(repo, "ls-files", "--stage", "-z").split(b"\0"):
        if entry.startswith(b"160000 "):
            submodules.add(entry.split(b"\t", 1)[1].decode("utf-8", "surrogateescape"))
    blobs = [f":{path}" for path in paths if path not in submodules]
    for name, kind, body in _batch(repo, blobs):
        found = words.find_bytes(body)
        if found and kind == "blob":
            problems.append(f"{name[1:]}: {', '.join(found)}")
    return problems


def check_message(repo: Path, message: Path, words: StopWords) -> list[str]:
    """Problems in a commit message (comment lines aside) and in the author
    and committer identities the commit will carry."""
    text = message.read_text(encoding="utf-8", errors="replace")
    problems = []
    found = words.find("\n".join(line for line in text.splitlines() if not line.startswith("#")))
    if found:
        problems.append(f"commit message: {', '.join(found)}")
    for variable in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"):
        identity = _git(repo, "var", variable).decode("utf-8", "replace")
        found = words.find(identity.rsplit(">", 1)[0])
        if found:
            problems.append(f"{variable.lower()[4:]}: {', '.join(found)}")
    return problems


def check_objects(repo: Path, revisions: list[str], words: StopWords) -> tuple[list[str], int, int]:
    """Problems in every object `git rev-list --objects revisions` names:
    commit and tag messages with their identities, paths, blob contents. Also
    how many commits and blobs were read."""
    paths: dict[str, set[str]] = {}
    for line in _git(repo, "rev-list", "--objects", *revisions).decode("utf-8", "surrogateescape").splitlines():
        sha, _, path = line.partition(" ")
        names = paths.setdefault(sha, set())
        if path:
            names.add(path)
    problems = []
    for path in sorted({path for names in paths.values() for path in names}):
        found = words.find(path)
        if found:
            problems.append(f"path {path}: {', '.join(found)}")
    commits = blobs = 0
    checked = {name for names in paths.values() for path in names for name in path.split("/")}
    for sha, kind, body in _batch(repo, list(paths)):
        if kind == "tree":
            # rev-list names each object once: a blob under two names (a
            # copy, a rename) shows the second only in its tree.
            for name, entry in _tree_names(body):
                if name not in checked:
                    checked.add(name)
                    found = words.find(name)
                    if found:
                        problems.append(f"path {name} (object {entry[:10]}): {', '.join(found)}")
            continue
        commits += kind == "commit"
        blobs += kind == "blob"
        found = words.find_bytes(body)
        if not found:
            continue
        if kind == "blob":
            where = ", ".join(sorted(paths[sha]))
            problems.append(f"blob {sha[:10]} ({where}): {', '.join(found)}")
        else:
            problems.append(f"{kind} {sha[:10]} (message or identity): {', '.join(found)}")
    return problems, commits, blobs


def check_history(repo: Path, words: StopWords, every_ref: bool = False) -> tuple[list[str], int, int]:
    """Problems in everything reachable from the branches and tags."""
    return check_objects(repo, ["--all"] if every_ref else ["--branches", "--tags"], words)


def check_push(repo: Path, remote: str, updates: str, words: StopWords) -> tuple[list[str], int, int]:
    """Problems in what a push sends, from the pre-push hook's lines
    `<local ref> <local sha> <remote ref> <remote sha>`."""
    sending = []
    exclude = []
    for line in updates.splitlines():
        parts = line.split()
        if len(parts) != 4 or parts[1] == _ZERO:
            continue
        sending.append(parts[1])
        if parts[3] != _ZERO and _exists(repo, parts[3]):
            exclude.append(parts[3])
    if not sending:
        return [], 0, 0
    remotes = [f"--remotes={remote}"] if _is_remote(repo, remote) else []
    return check_objects(repo, [*sending, "--not", *exclude, *remotes], words)


def _exists(repo: Path, sha: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "cat-file", "-e", sha], capture_output=True).returncode == 0


def _is_remote(repo: Path, name: str) -> bool:
    return name in _git(repo, "remote").decode().split()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stop_words", description=__doc__.split("\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check").add_argument("root", nargs="?", type=Path, default=Path("."))
    commands.add_parser("staged").add_argument("repo", nargs="?", type=Path, default=Path("."))
    message = commands.add_parser("message")
    message.add_argument("file", type=Path)
    message.add_argument("repo", nargs="?", type=Path, default=Path("."))
    history = commands.add_parser("history")
    history.add_argument("repo", nargs="?", type=Path, default=Path("."))
    history.add_argument("--all", action="store_true", help="every ref, remote-tracking ones included")
    push = commands.add_parser("push")
    push.add_argument("remote")
    push.add_argument("repo", nargs="?", type=Path, default=Path("."))
    commands.add_parser("where").add_argument("root", nargs="?", type=Path, default=Path("."))
    args = parser.parse_args(argv)

    root = (args.root if hasattr(args, "root") else args.repo).resolve()
    words = load(root)
    if words is None:
        print(not_performed(root), file=sys.stderr)
        if args.command != "where" and required(args.command):
            print(f"{NOT_PERFORMED} counts as a failure in CI and before a push", file=sys.stderr)
            return 1
        return 0
    if args.command == "where":
        print(f"{words.source}: {len(words.words)} stop words, {len(words.allowed)} allowed texts")
        return 0
    try:
        if args.command == "check":
            problems, what = check_tree(root, words), root.name
        elif args.command == "staged":
            problems, what = check_staged(root, words), "the staged changes"
        elif args.command == "message":
            problems, what = check_message(root, args.file, words), "the commit message"
        elif args.command == "history":
            problems, commits, blobs = check_history(root, words, args.all)
            what = f"the history of {root.name} ({commits} commits, {blobs} blobs)"
        else:
            problems, commits, blobs = check_push(root, args.remote, sys.stdin.read(), words)
            what = f"the push to {args.remote} ({commits} commits, {blobs} blobs)"
    except GitObjectError as error:
        print(f"STOP-WORD CHECK FAILED: {error}", file=sys.stderr)
        return 1
    for problem in problems:
        print(problem)
    print(f"{len(problems)} stop words in {what}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
