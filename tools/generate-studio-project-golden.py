#!/usr/bin/env python3
"""Emit the Studio project inspection corpus from the Python oracle.

The fixtures live in retrolarium_core/tests/fixtures/studio_projects and all
share one project root, so the corpus can record every path relative to it and
stay machine independent.

The disassembly manifest is stubbed, exactly as the Kit's own tests stub it.
Validating a manifest means rebuilding and hashing a ROM, which is not what
this corpus pins: it pins the project-file contract, which is all the C++
loader implements so far. The manifest cross-checks stay in the Kit until
contracts.py is ported.

Usage:
    python retrolarium_core/tools/generate-studio-project-golden.py <out.txt> [--check]
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tomllib
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "retrolarium_kit" / "src"))

FIXTURES = REPO_ROOT / "retrolarium_core" / "tests" / "fixtures" / "studio_projects"

SCHEMA = "retrolarium.studio-project-golden"
SCHEMA_VERSION = 1

# The token the corpus stores in place of the fixture directory, which differs
# on every machine.
ROOT_TOKEN = "<root>"


def stub_manifest(path: Path, platform: str, sha256: str) -> dict[str, object]:
    return {
        "schema": f"retrolarium.{platform}.disassembly",
        "input": {"sha256": sha256},
    }


def load(project: Path) -> dict[str, object]:
    from retrolarium_kit.studio_project import load_studio_project

    try:
        source = tomllib.loads(project.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        # A fixture that is not valid TOML fails in the loader, long before the
        # manifest matters, so any stub will do.
        source = {}
    platform = str(source.get("project", {}).get("platform", "nes"))
    sha256 = str(source.get("source", {}).get("sha256", ""))
    with mock.patch(
        "retrolarium_kit.studio_project.load_disassembly_manifest",
        return_value=stub_manifest(project, platform, sha256),
    ):
        return load_studio_project(project)


def relativise(value: object, root: Path) -> object:
    """Replace the absolute fixture paths with root-relative posix ones."""
    if isinstance(value, dict):
        return {key: relativise(item, root) for key, item in value.items()}
    if isinstance(value, list):
        return [relativise(item, root) for item in value]
    if not isinstance(value, str):
        return value
    candidate = Path(value)
    if not candidate.is_absolute():
        return value
    try:
        relative = candidate.resolve().relative_to(root)
    except ValueError:
        return value
    if relative == Path("."):
        return ROOT_TOKEN
    return f"{ROOT_TOKEN}/{relative.as_posix()}"


def accept_cases() -> list[str]:
    return sorted(path.name for path in FIXTURES.glob("accept-*.rlj"))


def reject_cases() -> list[str]:
    return sorted(path.name for path in FIXTURES.glob("reject-*.rlj"))


def render() -> str:
    from retrolarium_kit.studio_project import StudioProjectError

    root = FIXTURES.resolve()
    lines = [
        f"schema {SCHEMA}",
        f"schema_version {SCHEMA_VERSION}",
        "generator retrolarium_kit.studio_project",
        f"fixtures {FIXTURES.relative_to(REPO_ROOT).as_posix()}",
    ]

    for name in accept_cases():
        inspection = relativise(load(FIXTURES / name), root)
        rendered = json.dumps(inspection, indent=2, sort_keys=True)
        lines.append(f"accept {name}")
        lines.append("projection " + rendered.encode("utf-8").hex())
        lines.append("end")

    for name in reject_cases():
        try:
            load(FIXTURES / name)
        except StudioProjectError as error:
            message = str(error)
        else:
            raise SystemExit(f"{name} was accepted but the corpus expects a refusal")
        if str(root) in message:
            raise SystemExit(
                f"{name}: the refusal names an absolute path, which cannot be pinned"
            )
        lines.append(f"reject {name}")
        lines.append("message " + message.encode("utf-8").hex())
        lines.append("end")

    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    check = "--check" in argv[1:]
    positional = [value for value in argv[1:] if not value.startswith("-")]
    if len(positional) != 1:
        print(__doc__, file=sys.stderr)
        return 2

    corpus = render()
    output = Path(positional[0])

    if check:
        if not output.is_file():
            print(f"{output}: missing", file=sys.stderr)
            return 1
        if output.read_text(encoding="utf-8") != corpus:
            print(
                f"{output} is stale; rerun without --check to regenerate",
                file=sys.stderr,
            )
            return 1
        print(f"{output}: up to date")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(corpus, encoding="utf-8", newline="\n")
    print(
        f"{output}: {len(accept_cases())} projects, {len(reject_cases())} refusals"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
