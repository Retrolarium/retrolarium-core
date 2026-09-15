#!/usr/bin/env python3
"""Emit the cross-language iNES parity corpus from the Python oracle.

The C++ core must agree byte for byte with ``retrolarium_kit.ines``. Rather
than committing ROM fixtures, each case is described by its 16 header bytes
plus a seed; both sides materialise the body with the documented LCG below,
so a disagreement about the body shows up as a SHA-256 mismatch.

Usage:
    python retrolarium_core/tools/generate-ines-golden.py <output.txt>
"""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "retrolarium_kit" / "src"))

from retrolarium_kit.ines import (  # noqa: E402
    InesError,
    parse_ines,
    parse_ines_prefix,
)

SCHEMA = "retrolarium.ines-golden"
SCHEMA_VERSION = 1


def fill(seed: int, size: int) -> bytes:
    """Deterministic body bytes. Mirrored in ines_golden_test.cpp."""

    state = seed & 0x7FFFFFFF
    out = bytearray(size)
    for index in range(size):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        out[index] = (state >> 16) & 0xFF
    return bytes(out)


def header(
    prg_units: int,
    chr_units: int,
    flags6: int = 0,
    flags7: int = 0,
) -> bytes:
    return bytes([0x4E, 0x45, 0x53, 0x1A, prg_units, chr_units, flags6, flags7]) + bytes(8)


def body_size(head: bytes) -> int:
    trainer = 512 if head[6] & 0x04 else 0
    return trainer + head[4] * 0x4000 + head[5] * 0x2000


CASES: list[tuple[str, bytes, int]] = [
    ("nrom-16k-prg-8k-chr", header(1, 1), 1),
    ("nrom-32k-prg-8k-chr-vertical", header(2, 1, flags6=0x01), 7),
    ("mapper3-32k-prg-32k-chr-battery", header(2, 4, flags6=0x32), 1234),
    ("mapper1-64k-prg-no-chr", header(4, 0, flags6=0x10), 99),
    ("four-screen-with-trainer", header(1, 1, flags6=0x0C), 555),
    ("mapper66-high-nibble", header(2, 2, flags6=0x20, flags7=0x40), 4096),
]

ERROR_CASES: list[tuple[str, bytes, str]] = [
    ("missing-magic", b"NOPE" + bytes(12), "missing iNES magic"),
    ("truncated-header", b"NES\x1a\x01", "missing iNES magic"),
    ("nes20", header(1, 1, flags7=0x08), "NES 2.0"),
    ("zero-prg", header(0, 1), "no PRG ROM"),
]


def emit_case(lines: list[str], name: str, head: bytes, seed: int) -> None:
    payload = head + fill(seed, body_size(head))
    image = parse_ines(payload)

    lines.append(f"case {name}")
    lines.append(f"header {head.hex()}")
    lines.append(f"body-seed {seed}")
    lines.append(f"body-size {body_size(head)}")
    lines.append(f"expect-sha256 {image.sha256}")
    lines.append(f"expect-mapper {image.mapper}")
    lines.append(f"expect-mirroring {image.mirroring}")
    lines.append(f"expect-battery {int(image.battery)}")
    lines.append(f"expect-trainer-size {len(image.trainer)}")
    lines.append(f"expect-prg-size {len(image.prg)}")
    lines.append(f"expect-chr-size {len(image.chr)}")
    for entry in image.regions:
        lines.append(
            f"region {entry.name} {entry.file_offset} {entry.size} {entry.sha256}"
        )

    # The same bytes followed by trailing data must still parse as a prefix.
    trailer = b"\xde\xad\xbe\xef"
    prefix_image, rest = parse_ines_prefix(payload + trailer)
    if prefix_image.sha256 != image.sha256 or rest != trailer:
        raise SystemExit(f"prefix parse disagreed with whole-image parse for {name}")
    lines.append(f"expect-prefix-trailer {trailer.hex()}")
    lines.append("end")


def emit_error_case(lines: list[str], name: str, payload: bytes, needle: str) -> None:
    try:
        parse_ines(payload)
    except InesError as error:
        message = str(error)
    else:
        raise SystemExit(f"error case {name} unexpectedly parsed")
    if needle not in message:
        raise SystemExit(f"error case {name} reported {message!r}, wanted {needle!r}")

    lines.append(f"error-case {name}")
    lines.append(f"bytes {payload.hex()}")
    lines.append(f"expect-error {needle}")
    lines.append("end")


def render() -> str:
    lines = [
        f"schema {SCHEMA}",
        f"schema_version {SCHEMA_VERSION}",
        "generator retrolarium_kit.ines",
    ]
    for name, head, seed in CASES:
        emit_case(lines, name, head, seed)
    for name, payload, needle in ERROR_CASES:
        emit_error_case(lines, name, payload, needle)
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
        # Guards against the oracle changing without the committed corpus being
        # regenerated, which would let the C++ port drift unnoticed.
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
    print(f"{output}: {len(CASES)} cases, {len(ERROR_CASES)} error cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
