"""The code formatters shared by Retrolarium's repositories and the game
repositories.

`run` formats (or with check, only checks) the files Git tracks, each language
with its usual formatter:

| Files | Formatter | Default settings |
| --- | --- | --- |
| `*.md` | mdformat with mdformat-gfm | wrap 80, numbered lists |
| `*.py` | ruff format | `format_defaults/ruff.toml` |
| `*.c`, `*.cpp`, `*.h`, `*.hpp` | clang-format | `format_defaults/clang-format.yaml` |
| `*.lua` | StyLua | `format_defaults/stylua.toml` |
| `*.ps1`, `*.psm1`, `*.psd1` | PSScriptAnalyzer's Invoke-Formatter | `format_defaults/PSScriptAnalyzerSettings.psd1` |
| `*.json` | Prettier | `format_defaults/prettier.json` |
| `*.toml`, `*.rlj` | Taplo | `format_defaults/taplo.toml` |
| `*.java` | google-java-format | AOSP style (four spaces) |
| `*.sh` | shfmt | four spaces |

A repository's own configuration (`.mdformat.toml`, `ruff.toml` or
`pyproject.toml`, `.clang-format`, `stylua.toml`, `PSScriptAnalyzerSettings.psd1`,
`.prettierrc.json`, `.taplo.toml`) replaces the default. Trees named
`third_party` and the paths listed in a `.formatignore` at the repository root
(one Git pathspec glob or folder a line, `#` comments) are left alone.

A formatter that is not installed is reported in capitals and skipped, so a
missing tool never blocks a commit; `missing_tools` names them. The tools come
from pip (mdformat, mdformat-gfm, ruff, clang-format, shfmt-py), npm
(prettier, @taplo/cli, @johnnymorganz/stylua-bin), the PowerShell Gallery
(PSScriptAnalyzer) and google-java-format's release jar, found through
RETROLARIUM_JAVA_FORMAT or in %LOCALAPPDATA%/Retrolarium/formatters.

    python -m retrolarium_core.formatting [REPO] [--check]
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import fnmatch
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Callable

DEFAULTS = Path(__file__).resolve().parent / "format_defaults"
# Command lines stay below Windows' 32 767-character limit.
BATCH = 100


@dataclass(frozen=True)
class Language:
    name: str
    patterns: tuple[str, ...]
    configs: tuple[str, ...]
    run: Callable[[Path, list[str], bool, bool], tuple[int, list[str]]]
    missing: Callable[[], str | None]


def _git_files(repo: Path) -> list[str]:
    """The files Git tracks; none outside a Git checkout."""
    listed = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True)
    if listed.returncode:
        return []
    return [os.fsdecode(raw) for raw in listed.stdout.split(b"\0") if raw]


def _ignored(repo: Path) -> list[str]:
    patterns = ["third_party/*", "*/third_party/*"]
    ignore = repo / ".formatignore"
    if ignore.is_file():
        for line in ignore.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line.rstrip("/") + "/*" if not any(c in line for c in "*?[") else line)
    return patterns


def files_for(repo: Path, patterns: tuple[str, ...], tracked: list[str] | None = None) -> list[str]:
    """The tracked files matching one of the patterns, minus the ignored ones."""
    ignored = _ignored(repo)
    chosen = []
    for name in _git_files(repo) if tracked is None else tracked:
        base = name.rsplit("/", 1)[-1]
        if not any(fnmatch.fnmatch(base, pattern) for pattern in patterns):
            continue
        if any(fnmatch.fnmatch(name, pattern) for pattern in ignored):
            continue
        if (repo / name).is_file():
            chosen.append(name)
    return chosen


def _has(repo: Path, names: tuple[str, ...]) -> bool:
    return any((repo / name).is_file() for name in names)


def _batches(files: list[str]):
    for start in range(0, len(files), BATCH):
        yield files[start : start + BATCH]


def _call(command: list[str], repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _changed_by_compare(repo: Path, files: list[str], format_text: Callable[[str, str], str], check: bool) -> list[str]:
    """Format each file through a text function; write it, or only list it."""
    changed = []
    for name in files:
        path = repo / name
        original = path.read_bytes().decode("utf-8")
        formatted = format_text(name, original)
        if formatted != original:
            changed.append(name)
            if not check:
                path.write_bytes(formatted.encode("utf-8"))
    return changed


# --- the tools ---------------------------------------------------------------


def _module_missing(module: str, install: str) -> Callable[[], str | None]:
    def missing() -> str | None:
        try:
            __import__(module)
        except ImportError:
            return f"{install}"
        return None

    return missing


def _program_missing(program: str, install: str) -> Callable[[], str | None]:
    return lambda: None if shutil.which(program) else install


def _markdown(repo: Path, files: list[str], check: bool, own: bool) -> tuple[int, list[str]]:
    import mdformat
    import tomllib

    options = {"wrap": 80, "number": True}
    if own:
        options = tomllib.loads((repo / ".mdformat.toml").read_text(encoding="utf-8"))
    return 0, _changed_by_compare(
        repo, files, lambda name, text: mdformat.text(text, options=options, extensions={"gfm", "tables"}), check
    )


def _python(repo: Path, files: list[str], check: bool, own: bool) -> tuple[int, list[str]]:
    options = [] if own else ["--config", str(DEFAULTS / "ruff.toml")]
    ruff = shutil.which("ruff")

    def format_text(name: str, text: str) -> str:
        result = subprocess.run(
            [ruff, "format", *options, "--stdin-filename", name, "-"],
            input=text.encode("utf-8"),
            capture_output=True,
            cwd=repo,
            check=True,
        )
        return result.stdout.decode("utf-8")

    return 0, _changed_by_compare(repo, files, format_text, check)


def _clang(repo: Path, files: list[str], check: bool, own: bool) -> tuple[int, list[str]]:
    style = "file" if own else f"file:{DEFAULTS / 'clang-format.yaml'}"
    program = shutil.which("clang-format")

    def format_text(name: str, text: str) -> str:
        result = subprocess.run(
            [program, f"--style={style}", f"--assume-filename={name}"],
            input=text.encode("utf-8"),
            capture_output=True,
            cwd=repo,
            check=True,
        )
        return result.stdout.decode("utf-8")

    return 0, _changed_by_compare(repo, files, format_text, check)


def _lua(repo: Path, files: list[str], check: bool, own: bool) -> tuple[int, list[str]]:
    options = [] if own else ["--config-path", str(DEFAULTS / "stylua.toml")]
    stylua = shutil.which("stylua")

    def format_text(name: str, text: str) -> str:
        result = subprocess.run(
            [stylua, *options, "--stdin-filepath", name, "-"],
            input=text.encode("utf-8"),
            capture_output=True,
            cwd=repo,
            check=True,
        )
        return result.stdout.decode("utf-8")

    return 0, _changed_by_compare(repo, files, format_text, check)


def _powershell(repo: Path, files: list[str], check: bool, own: bool) -> tuple[int, list[str]]:
    settings = repo / "PSScriptAnalyzerSettings.psd1" if own else DEFAULTS / "PSScriptAnalyzerSettings.psd1"
    script = (
        "param([string]$Settings, [string]$Folder)\n"
        "Import-Module PSScriptAnalyzer\n"
        "Get-ChildItem -LiteralPath $Folder -File | ForEach-Object {\n"
        "  $text = [IO.File]::ReadAllText($_.FullName)\n"
        "  $out = Invoke-Formatter -ScriptDefinition $text -Settings $Settings\n"
        "  [IO.File]::WriteAllText($_.FullName + '.out', $out, (New-Object Text.UTF8Encoding $false))\n"
        "}\n"
    )
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        (folder / "format.ps1").write_text(script, encoding="utf-8")
        work = folder / "files"
        work.mkdir()
        for index, name in enumerate(files):
            (work / f"{index}.ps1").write_bytes((repo / name).read_bytes())
        result = _call(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(folder / "format.ps1"),
                "-Settings",
                str(settings),
                "-Folder",
                str(work),
            ],
            repo,
        )
        if result.returncode:
            return 1, [result.stderr.strip() or result.stdout.strip()]
        formatted = {
            name: (work / f"{index}.ps1.out").read_bytes().decode("utf-8").replace("\r\n", "\n")
            for index, name in enumerate(files)
        }
    return 0, _changed_by_compare(repo, files, lambda name, text: formatted[name], check)


def _json(repo: Path, files: list[str], check: bool, own: bool) -> tuple[int, list[str]]:
    options = [] if own else ["--config", str(DEFAULTS / "prettier.json")]
    prettier = shutil.which("prettier")
    changed = []
    for batch in _batches(files):
        result = _call([prettier, "--list-different", "--no-editorconfig", *options, *batch], repo)
        changed.extend(line.strip().replace(os.sep, "/") for line in result.stdout.splitlines() if line.strip())
        if result.returncode not in (0, 1):
            return 1, [result.stderr.strip()]
        if not check and result.returncode == 1:
            _call([prettier, "--write", "--no-editorconfig", *options, *batch], repo)
    return 0, changed


def _toml(repo: Path, files: list[str], check: bool, own: bool) -> tuple[int, list[str]]:
    options = [] if own else ["--config", str(DEFAULTS / "taplo.toml")]
    taplo = shutil.which("taplo")

    def format_text(name: str, text: str) -> str:
        result = subprocess.run(
            [taplo, "fmt", *options, "-"], input=text.encode("utf-8"), capture_output=True, cwd=repo, check=True
        )
        return result.stdout.decode("utf-8")

    return 0, _changed_by_compare(repo, files, format_text, check)


def java_format_jar() -> Path | None:
    named = os.environ.get("RETROLARIUM_JAVA_FORMAT")
    if named:
        return Path(named) if Path(named).is_file() else None
    folder = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "Retrolarium" / "formatters"
    jars = sorted(folder.glob("google-java-format-*-all-deps.jar"))
    return jars[-1] if jars else None


def _java(repo: Path, files: list[str], check: bool, own: bool) -> tuple[int, list[str]]:
    jar = java_format_jar()
    changed = []
    for batch in _batches(files):
        result = _call(["java", "-jar", str(jar), "--aosp", "--dry-run", *batch], repo)
        if result.returncode:
            return 1, [result.stderr.strip()]
        stale = [line.strip().replace(os.sep, "/") for line in result.stdout.splitlines() if line.strip()]
        changed.extend(stale)
        if stale and not check:
            _call(["java", "-jar", str(jar), "--aosp", "--replace", *stale], repo)
    return 0, changed


def _shell(repo: Path, files: list[str], check: bool, own: bool) -> tuple[int, list[str]]:
    result = _call(["shfmt", "-i", "4", "-l", *files], repo)
    changed = [line.strip().replace(os.sep, "/") for line in result.stdout.splitlines() if line.strip()]
    if changed and not check:
        _call(["shfmt", "-i", "4", "-w", *changed], repo)
    return 0, changed


def _powershell_missing() -> str | None:
    if not shutil.which("powershell"):
        return "PowerShell"
    found = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "if (Get-Module -ListAvailable PSScriptAnalyzer) { 'yes' }",
        ],
        capture_output=True,
        text=True,
    )
    return None if "yes" in found.stdout else "Install-Module PSScriptAnalyzer -Scope CurrentUser"


LANGUAGES = (
    Language(
        "Markdown",
        ("*.md",),
        (".mdformat.toml",),
        _markdown,
        _module_missing("mdformat", "pip install mdformat mdformat-gfm mdformat-tables"),
    ),
    Language("Python", ("*.py",), ("ruff.toml", ".ruff.toml"), _python, _program_missing("ruff", "pip install ruff")),
    Language(
        "C and C++",
        ("*.c", "*.cc", "*.cpp", "*.h", "*.hpp"),
        (".clang-format",),
        _clang,
        _program_missing("clang-format", "pip install clang-format"),
    ),
    Language(
        "Lua",
        ("*.lua",),
        ("stylua.toml", ".stylua.toml"),
        _lua,
        _program_missing("stylua", "npm install -g @johnnymorganz/stylua-bin"),
    ),
    Language(
        "PowerShell",
        ("*.ps1", "*.psm1", "*.psd1"),
        ("PSScriptAnalyzerSettings.psd1",),
        _powershell,
        _powershell_missing,
    ),
    Language(
        "JSON",
        ("*.json",),
        (".prettierrc", ".prettierrc.json"),
        _json,
        _program_missing("prettier", "npm install -g prettier"),
    ),
    Language(
        "TOML",
        ("*.toml", "*.rlj"),
        (".taplo.toml", "taplo.toml"),
        _toml,
        _program_missing("taplo", "npm install -g @taplo/cli"),
    ),
    Language(
        "Java",
        ("*.java",),
        (),
        _java,
        lambda: (
            None
            if shutil.which("java") and java_format_jar()
            else "java and google-java-format's all-deps jar (RETROLARIUM_JAVA_FORMAT)"
        ),
    ),
    Language("shell", ("*.sh",), (), _shell, _program_missing("shfmt", "pip install shfmt-py")),
)


def _own_config(repo: Path, language: Language) -> bool:
    if _has(repo, language.configs):
        return True
    if language.name == "Python" and (repo / "pyproject.toml").is_file():
        return "[tool.ruff" in (repo / "pyproject.toml").read_text(encoding="utf-8")
    return False


@dataclass(frozen=True)
class Result:
    language: str
    files: int
    changed: tuple[str, ...] = ()
    missing: str | None = None
    error: str | None = None


def results(repo: Path, check: bool = False) -> list[Result]:
    """Format the repository (with check, only find what would change), one
    result a language that has files."""
    repo = repo.resolve()
    tracked = _git_files(repo)
    found = []
    for language in LANGUAGES:
        files = files_for(repo, language.patterns, tracked)
        if not files:
            continue
        missing = language.missing()
        if missing:
            found.append(Result(language.name, len(files), missing=missing))
            continue
        status, changed = language.run(repo, files, check, _own_config(repo, language))
        if status:
            found.append(Result(language.name, len(files), error=" ".join(changed)))
        else:
            found.append(Result(language.name, len(files), tuple(changed)))
    return found


def run(repo: Path, check: bool = False, out=sys.stderr) -> int:
    """Format the repository (with check, only list what would change);
    nonzero when check finds a file to change or a formatter fails."""
    failed = False
    for result in results(repo, check):
        if result.missing:
            print(f"{result.language.upper()} FORMAT NOT CHECKED: install {result.missing}", file=out)
        elif result.error:
            print(f"[ERROR] {result.language}: {result.error}", file=out)
            failed = True
        elif result.changed:
            verb = "would change" if check else "formatted"
            print(
                f"[{'FAIL' if check else 'OK'}] {result.language}: {verb} {len(result.changed)} of "
                f"{result.files} file(s)",
                file=out,
            )
            for name in result.changed[:20]:
                print(f"    {name}", file=out)
            failed |= check
        else:
            print(f"[OK] {result.language}: {result.files} file(s) formatted", file=out)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="formatting", description=__doc__.split("\n", 1)[0])
    parser.add_argument("repo", nargs="?", type=Path, default=Path("."))
    parser.add_argument("--check", action="store_true", help="report, change nothing")
    args = parser.parse_args(argv)
    return run(args.repo, args.check)


if __name__ == "__main__":
    raise SystemExit(main())
