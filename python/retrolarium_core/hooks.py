"""Git hooks shared by Retrolarium's repositories and the game repositories.

`install` writes three small hooks into a repository; each runs this module
with the Python and the retrolarium_core it was installed from:

- pre-commit: the stop words in the staged changes (retrolarium_core.stop_words),
  then `make lint` and `make format-check` when the repository's Makefile
  has those targets;
- commit-msg: the stop words in the message and the author and committer
  identities;
- pre-push: the stop words in everything the push sends.

Without a stop-word list the hooks say in capitals that the stop words were
not checked, and go on. `git commit --no-verify` and `git push --no-verify`
skip them. RETROLARIUM_HOOKS_MAKE=0 skips the make targets. `--env NAME=VALUE`
(repeatable) sets a variable for the hooks and the make targets they run; the
kit's `rltool hooks install` sets RLTOOL that way, for the game repositories.

`markdown` formats the Markdown files Git tracks (third_party trees aside) with
mdformat and its mdformat-gfm plugin, as the repository's .mdformat.toml says;
--check only reports. Without mdformat it says in capitals that nothing was
checked. A Makefile can run this file by its path, without PYTHONPATH.

    python -m retrolarium_core.hooks install [REPO] [--force] [--env NAME=VALUE]...
    python -m retrolarium_core.hooks uninstall [REPO]
    python -m retrolarium_core.hooks markdown [REPO] [--check]
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

if not __package__:  # run by its path, as a Makefile does
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from retrolarium_core import stop_words  # noqa: E402

HOOKS = ("pre-commit", "commit-msg", "pre-push")
MARKER = "# retrolarium_core.hooks"
MAKE_TARGETS = ("lint", "format-check")
_CORE = Path(__file__).resolve().parents[1]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def hooks_folder(repo: Path) -> Path:
    folder = Path(_git(repo, "rev-parse", "--git-path", "hooks"))
    return folder if folder.is_absolute() else (repo / folder).resolve()


def _quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def script(hook: str, environment: dict[str, str] | None = None) -> str:
    python = Path(sys.executable).as_posix()
    core = _CORE.as_posix()
    separator = ";" if os.name == "nt" else ":"
    exports = "".join(f"export {name}={_quote(value)}\n" for name, value in sorted((environment or {}).items()))
    return f"""#!/bin/sh
{MARKER}: reinstall with python -m retrolarium_core.hooks install
if [ ! -x "{python}" ] && [ ! -f "{python}" ]; then
    echo "RETROLARIUM HOOKS NOT RUN: {python} is gone; reinstall them" >&2
    exit 0
fi
{exports}PYTHONPATH="{core}${{PYTHONPATH:+{separator}$PYTHONPATH}}" exec "{python}" -m retrolarium_core.hooks run {hook} "$@"
"""


def install(repo: Path, force: bool = False, environment: dict[str, str] | None = None) -> list[Path]:
    folder = hooks_folder(repo)
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for hook in HOOKS:
        path = folder / hook
        if path.exists() and MARKER not in path.read_text(encoding="utf-8", errors="replace") and not force:
            raise SystemExit(f"{path} is not ours; move it away or pass --force")
        path.write_text(script(hook, environment), encoding="utf-8", newline="\n")
        path.chmod(0o755)
        written.append(path)
    return written


def uninstall(repo: Path) -> list[Path]:
    removed = []
    for hook in HOOKS:
        path = hooks_folder(repo) / hook
        if path.exists() and MARKER in path.read_text(encoding="utf-8", errors="replace"):
            path.unlink()
            removed.append(path)
    return removed


def make_targets(repo: Path) -> list[str]:
    """The targets of MAKE_TARGETS the repository's Makefile defines, its
    included files counted: make itself is asked (a dry run), or without make
    the Makefile is read."""
    makefile = repo / "Makefile"
    if not makefile.is_file():
        return []
    make = shutil.which("make")
    if make is None:
        text = makefile.read_text(encoding="utf-8", errors="replace")
        return [target for target in MAKE_TARGETS if re.search(rf"^{re.escape(target)}\s*:", text, re.MULTILINE)]
    found = []
    # make's messages in the C locale (a translated make words them
    # otherwise), and any quoting: GNU make 3.81 writes `target'.
    environment = dict(os.environ, LC_ALL="C", LANGUAGE="C")
    for target in MAKE_TARGETS:
        result = subprocess.run([make, "-n", "-s", target], cwd=repo, capture_output=True, text=True,
                                errors="replace", env=environment)
        if not re.search(rf"No rule to make target .{re.escape(target)}'", result.stderr):
            found.append(target)
    return found


def markdown(repo: Path, check: bool) -> int:
    """Format (or with check, only check) the tracked Markdown files."""
    listed = _git(repo, "ls-files", "-z", "--", "*.md", ":!:third_party/**", ":!:**/third_party/**")
    files = [name for name in listed.split("\0") if name]
    if not files:
        return 0
    try:
        import mdformat  # noqa: F401
    except ImportError:
        print("MARKDOWN FORMAT NOT CHECKED: mdformat is not installed "
              "(pip install mdformat mdformat-gfm)", file=sys.stderr)
        return 0
    command = [sys.executable, "-m", "mdformat", *(["--check"] if check else []), *files]
    return subprocess.run(command, cwd=repo).returncode


def _stop_words(*args: str, stdin: str | None = None) -> int:
    command = [sys.executable, "-m", "retrolarium_core.stop_words", *args]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, [str(_CORE), environment.get("PYTHONPATH")]))
    return subprocess.run(command, input=stdin, text=True, env=environment).returncode


def run(hook: str, args: list[str], repo: Path) -> int:
    if hook == "pre-commit":
        failed = _stop_words("staged", str(repo)) != 0
        if os.environ.get("RETROLARIUM_HOOKS_MAKE", "1") != "0":
            targets = make_targets(repo)
            make = shutil.which("make")
            if targets and not make:
                print(f"RETROLARIUM HOOKS: no make, so {' and '.join(targets)} did not run", file=sys.stderr)
            for target in targets if make else []:
                print(f"== make {target}", file=sys.stderr)
                failed |= subprocess.run([make, "-s", target], cwd=repo).returncode != 0
        return 1 if failed else 0
    if hook == "commit-msg":
        return _stop_words("message", args[0], str(repo))
    if hook == "pre-push":
        return _stop_words("push", args[0], str(repo), stdin=sys.stdin.read())
    raise SystemExit(f"unknown hook {hook}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hooks", description=__doc__.split("\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)
    installing = commands.add_parser("install")
    installing.add_argument("repo", nargs="?", type=Path, default=Path("."))
    installing.add_argument("--force", action="store_true", help="replace hooks that are not ours")
    installing.add_argument("--env", action="append", default=[], metavar="NAME=VALUE",
                            help="a variable for the hooks and their make targets (repeatable)")
    commands.add_parser("uninstall").add_argument("repo", nargs="?", type=Path, default=Path("."))
    formatting = commands.add_parser("markdown")
    formatting.add_argument("repo", nargs="?", type=Path, default=Path("."))
    formatting.add_argument("--check", action="store_true", help="report, change nothing")
    running = commands.add_parser("run")
    running.add_argument("hook", choices=HOOKS)
    running.add_argument("args", nargs="*")
    args = parser.parse_args(argv)

    if args.command == "run":
        return run(args.hook, args.args, Path(_git(Path("."), "rev-parse", "--show-toplevel")))
    if args.command == "markdown":
        return markdown(args.repo.resolve(), args.check)
    repo = Path(_git(args.repo, "rev-parse", "--show-toplevel"))
    if args.command == "install":
        environment = dict(item.split("=", 1) for item in args.env)
        for path in install(repo, args.force, environment):
            print(f"installed {path}")
        if stop_words.locate(repo) is None:
            print(stop_words.not_performed(repo), file=sys.stderr)
    else:
        for path in uninstall(repo):
            print(f"removed {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
