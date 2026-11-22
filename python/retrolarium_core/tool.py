"""Locate and drive ``rlcore``, the command-line face of retrolarium_core.

The Mega Drive compressions (Nemesis, Enigma) live in the C++ core, because the
Kit and the Qt application both need them and a format must not have two
implementations.
The Kit reaches that code the same way it reaches ca65: by running a pinned
binary, not by linking or importing anything. That keeps this a pure Python
package with no compiler on the install path.

Resolution order, first hit wins:

1. ``RETROLARIUM_CORE`` - an explicit path; the Studio names the rlcore it
   ships this way, and CI pins one.
2. A payload shipped inside the wheel (``retrolarium_core/_core``), which is
   how an installed Kit finds it.
3. ``PATH``.
4. A build tree in a retrolarium-core checkout, only when
   ``RETROLARIUM_CORE_DEV=1``: a stale build beside an installed package is
   never picked up by accident.

The binary is pinned: before its first command in a process, ``rlcore version``
must report this package's ``__version__`` (CMakeLists.txt's project version,
which tests/python/test_version.py keeps equal), or ``CoreToolError`` names the
path and both versions.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Sequence

from retrolarium_core import __version__
from retrolarium_core.host import normalize_host

TOOL_NAME = "rlcore"
ENVIRONMENT_OVERRIDE = "RETROLARIUM_CORE"
DEVELOPMENT_SWITCH = "RETROLARIUM_CORE_DEV"
# The rlcore version this package drives.
RLCORE_VERSION = __version__


class CoreToolError(RuntimeError):
    """rlcore is unavailable, or it refused the request."""


def _executable_name() -> str:
    return f"{TOOL_NAME}.exe" if os.name == "nt" else TOOL_NAME


def _packaged_candidates() -> list[Path]:
    root = Path(__file__).resolve().parent / "_core"
    return [root / normalize_host() / _executable_name(), root / _executable_name()]


def _checkout_candidates() -> list[Path]:
    # Walk up far enough to find the repository root from either an installed
    # editable checkout or a source tree.
    here = Path(__file__).resolve()
    candidates: list[Path] = []
    for parent in list(here.parents)[:6]:
        for build in (parent / "build" / "core", parent / "retrolarium-core" / "build", parent / "build"):
            # retrolarium-core as a repository of its own: <repo>/build/rlcore;
            # a multi-configuration generator (Visual Studio) adds Release/ or
            # Debug/.
            for folder in (build, build / "Release", build / "RelWithDebInfo", build / "Debug"):
                candidates.append(folder / _executable_name())
    return candidates


def find_core_tool() -> Path:
    """Return the rlcore executable, or raise explaining where it was sought."""

    override = os.environ.get(ENVIRONMENT_OVERRIDE)
    if override:
        candidate = Path(override)
        if candidate.is_file():
            return candidate
        raise CoreToolError(f"{ENVIRONMENT_OVERRIDE} points at {candidate}, which is not a file")

    for candidate in _packaged_candidates():
        if candidate.is_file():
            return candidate

    found = shutil.which(TOOL_NAME)
    if found:
        return Path(found)

    if os.environ.get(DEVELOPMENT_SWITCH) == "1":
        for candidate in _checkout_candidates():
            if candidate.is_file():
                return candidate

    raise CoreToolError(
        f"{TOOL_NAME} was not found. Set {ENVIRONMENT_OVERRIDE} to the executable, or build retrolarium-core "
        f"and set {DEVELOPMENT_SWITCH}=1 to use its build tree."
    )


# Tools whose version matched, by path and file identity: checked once a
# process, again when the file changes.
_verified: set[tuple[str, int, int]] = set()


def _verified_tool() -> Path:
    tool = find_core_tool()
    status = tool.stat()
    key = (str(tool.resolve()), status.st_mtime_ns, status.st_size)
    if key in _verified:
        return tool
    reported = _version_of(tool)
    if reported != RLCORE_VERSION:
        raise CoreToolError(
            f"{tool} is {TOOL_NAME} {reported or '(no version)'}, but retrolarium_core {RLCORE_VERSION} needs "
            f"{TOOL_NAME} {RLCORE_VERSION}: rebuild it, or point {ENVIRONMENT_OVERRIDE} at a matching one"
        )
    _verified.add(key)
    return tool


def _execute(tool: Path, arguments: Sequence[str], timeout: float) -> subprocess.CompletedProcess:
    """Run rlcore; whatever goes wrong (it cannot start, it hangs, it prints
    bytes that are not UTF-8) is a CoreToolError, never another exception."""
    try:
        return subprocess.run(
            [str(tool), *arguments],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise CoreToolError(f"{TOOL_NAME} {' '.join(arguments)} did not finish within {timeout:g} s") from error
    except OSError as error:
        raise CoreToolError(f"{tool} could not be run: {error}") from error


def run(arguments: Sequence[str], *, timeout: float = 120.0) -> dict[str, object]:
    """Run one rlcore command and return its JSON result.

    Commands that report nothing return an empty mapping rather than failing,
    so a caller can treat "no output" and "no result" the same way. rlcore
    exits with 1 when it refuses the data, 2 on a usage error and 3 when a
    file cannot be read or written; each is a CoreToolError here.
    """

    tool = _verified_tool()
    completed = _execute(tool, arguments, timeout)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise CoreToolError(f"{TOOL_NAME} {' '.join(arguments)} failed with exit code {completed.returncode}: {detail}")
    output = completed.stdout.strip()
    if not output:
        return {}
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as error:
        raise CoreToolError(
            f"{TOOL_NAME} {' '.join(arguments)} produced output that is not JSON: {output[:200]}"
        ) from error
    if not isinstance(parsed, dict):
        raise CoreToolError(f"{TOOL_NAME} returned {type(parsed).__name__}, not an object")
    return parsed


def _version_of(tool: Path) -> str:
    completed = _execute(tool, ["version"], 30)
    if completed.returncode != 0:
        raise CoreToolError(f"{TOOL_NAME} version failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def version() -> str:
    """The version the rlcore found reports, whether or not it matches."""
    return _version_of(find_core_tool())


def nemesis_decompress(source: Path, output: Path) -> dict[str, object]:
    return run(["nemesis", "decompress", str(source), str(output)])


def nemesis_compress(plain: Path, reference: Path, output: Path) -> dict[str, object]:
    """Re-encode using the code table carried by `reference`.

    Nemesis has no standalone compressor, so a reference stream is required.
    Callers that want the original bytes back for unchanged content compare the
    decoded content themselves and reuse the reference verbatim.
    """
    return run(["nemesis", "compress", str(plain), str(reference), str(output)])


def enigma_decompress(source: Path, output: Path, base_tile: int = 0) -> dict[str, object]:
    arguments = ["enigma", "decompress", str(source), str(output)]
    if base_tile:
        arguments.append(str(base_tile))
    return run(arguments)


def enigma_compress(plain: Path, output: Path) -> dict[str, object]:
    return run(["enigma", "compress", str(plain), str(output)])


# The same codecs on bytes, for callers that hold the data in memory (the
# kit's Flicky graphics): rlcore reads and writes files in a scratch folder.


def _through_files(command: str, inputs: Sequence[bytes], extra: Sequence[str] = ()) -> bytes:
    with tempfile.TemporaryDirectory(prefix="rlcore-") as directory:
        folder = Path(directory)
        paths = []
        for index, data in enumerate(inputs):
            path = folder / f"input{index}.bin"
            path.write_bytes(data)
            paths.append(str(path))
        output = folder / "output.bin"
        family, verb = command.split()
        run([family, verb, *paths, str(output), *extra])
        return output.read_bytes()


def nemesis_decode(data: bytes) -> bytes:
    return _through_files("nemesis decompress", [data])


def nemesis_encode(plain: bytes, reference: bytes) -> bytes:
    """Re-encode `plain` with the code table of `reference` (the same tile count)."""
    return _through_files("nemesis compress", [plain, reference])


def enigma_decode(data: bytes, base_tile: int = 0) -> bytes:
    return _through_files("enigma decompress", [data], [str(base_tile)] if base_tile else [])


def enigma_encode(plain: bytes) -> bytes:
    return _through_files("enigma compress", [plain])
