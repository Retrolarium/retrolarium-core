"""Locate and drive ``rlcore``, the command-line face of retrolarium_core.

Container and compression codecs live in the C++ core, because the Kit and the
Qt application both need them and a format must not have two implementations.
The Kit reaches that code the same way it reaches ca65: by running a pinned
binary, not by linking or importing anything. That keeps this a pure Python
package with no compiler on the install path.

Resolution order, first hit wins:

1. ``RETROLARIUM_CORE`` - an explicit path, for development and for CI pinning.
2. A payload shipped inside the wheel, which is how an installed Kit finds it.
3. A build tree in this checkout, which is how a working copy finds it.
4. ``PATH``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Sequence

from retrolarium_core.host import normalize_host

TOOL_NAME = "rlcore"
ENVIRONMENT_OVERRIDE = "RETROLARIUM_CORE"


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
        candidates.append(parent / "build" / "core" / _executable_name())
        candidates.append(parent / "retrolarium-core" / "build" / _executable_name())
        # retrolarium-core as a repository of its own: <repo>/build/rlcore.
        candidates.append(parent / "build" / _executable_name())
    return candidates


def find_core_tool() -> Path:
    """Return the rlcore executable, or raise explaining where it was sought."""

    override = os.environ.get(ENVIRONMENT_OVERRIDE)
    if override:
        candidate = Path(override)
        if candidate.is_file():
            return candidate
        raise CoreToolError(
            f"{ENVIRONMENT_OVERRIDE} points at {candidate}, which is not a file"
        )

    for candidate in _packaged_candidates() + _checkout_candidates():
        if candidate.is_file():
            return candidate

    found = shutil.which(TOOL_NAME)
    if found:
        return Path(found)

    raise CoreToolError(
        f"{TOOL_NAME} was not found. Build retrolarium-core, or set "
        f"{ENVIRONMENT_OVERRIDE} to the executable."
    )


def run(arguments: Sequence[str], *, timeout: float = 120.0) -> dict[str, object]:
    """Run one rlcore command and return its JSON result.

    Commands that report nothing return an empty mapping rather than failing,
    so a caller can treat "no output" and "no result" the same way.
    """

    tool = find_core_tool()
    completed = subprocess.run(
        [str(tool), *arguments],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise CoreToolError(
            f"{TOOL_NAME} {' '.join(arguments)} failed with exit code "
            f"{completed.returncode}: {detail}"
        )
    output = completed.stdout.strip()
    if not output:
        return {}
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as error:
        raise CoreToolError(
            f"{TOOL_NAME} {' '.join(arguments)} produced output that is not JSON: "
            f"{output[:200]}"
        ) from error
    if not isinstance(parsed, dict):
        raise CoreToolError(f"{TOOL_NAME} returned {type(parsed).__name__}, not an object")
    return parsed


def version() -> str:
    tool = find_core_tool()
    completed = subprocess.run(
        [str(tool), "version"], capture_output=True, text=True, timeout=30, check=False
    )
    if completed.returncode != 0:
        raise CoreToolError(f"{TOOL_NAME} version failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def inspect_ines(image: Path) -> dict[str, object]:
    return run(["ines", "inspect", str(image)])


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
