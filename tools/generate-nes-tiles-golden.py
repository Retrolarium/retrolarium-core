#!/usr/bin/env python3
"""Emit the NES 2bpp character-data parity corpus from the Python oracle.

``retrolarium_kit.nes_resources`` still decodes and encodes CHR for the Kit's
own build path; the C++ port in retrolarium_core is what the editor will use.
While both exist a test has to hold them together, which is what this corpus is
for.

Payloads are generated here, not lifted from a ROM.

Usage:
    python retrolarium_core/tools/generate-nes-tiles-golden.py <output.txt> [--check]
"""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "retrolarium_kit" / "src"))

from retrolarium_kit.nes_resources import (  # noqa: E402
    decode_chr_2bpp,
    encode_chr_2bpp,
)
from retrolarium_kit.nes_visuals import (  # noqa: E402
    decode_metatiles,
    encode_metatiles,
)

SCHEMA = "retrolarium.nes-tiles-golden"
SCHEMA_VERSION = 1


def tile_bytes(low: list[int], high: list[int]) -> bytes:
    return bytes(low) + bytes(high)


def lcg(seed: int, size: int) -> bytes:
    """Same generator the iNES corpus uses, so bodies stay reproducible."""
    state = seed & 0x7FFFFFFF
    out = bytearray(size)
    for index in range(size):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        out[index] = (state >> 16) & 0xFF
    return bytes(out)


def flatten(tiles) -> str:
    """Serialise decoded tiles as one flat run of pixel digits."""
    digits = []
    for tile in tiles:
        for row in tile:
            digits.extend(str(pixel) for pixel in row)
    return "".join(digits)


def payload_cases() -> list[tuple[str, bytes]]:
    cases: list[tuple[str, bytes]] = []

    # No tiles at all: a valid, if empty, resource.
    cases.append(("empty", b""))

    # Every pixel zero, then every pixel three: both bitplanes off, then on.
    cases.append(("all-zero", tile_bytes([0] * 8, [0] * 8)))
    cases.append(("all-three", tile_bytes([0xFF] * 8, [0xFF] * 8)))

    # One bitplane at a time, which is where a bit-order mistake shows up.
    cases.append(("low-plane-only", tile_bytes([0xFF] * 8, [0x00] * 8)))
    cases.append(("high-plane-only", tile_bytes([0x00] * 8, [0xFF] * 8)))

    # A single pixel set in each corner, pinning the bit-to-column mapping.
    cases.append(("corners", tile_bytes(
        [0x80, 0, 0, 0, 0, 0, 0, 0x01], [0x01, 0, 0, 0, 0, 0, 0, 0x80])))

    # Each row a different value, so row order cannot be permuted unnoticed.
    cases.append(("row-ramp", tile_bytes(
        list(range(8)), [value << 4 for value in range(8)])))

    # Several tiles, so tile striding is covered too.
    cases.append(("four-tiles", lcg(7, 16 * 4)))

    # A larger run, the size of one CHR bank.
    cases.append(("full-bank", lcg(1234, 0x2000)))

    return cases


def metatile_cases() -> list[tuple[str, list[int], bytes]]:
    """Metatile record slicing, with the group layout the profile supplies.

    Only the slicing is in the core. How a game turns a metatile identifier
    into a group and a slot is game semantics and stays out of it.
    """

    cases: list[tuple[str, list[int], bytes]] = []
    layouts: list[tuple[str, list[str], list[int]]] = [
        ("single-group", ["palette_0"], [1]),
        ("four-groups", ["palette_0", "palette_1", "palette_2", "palette_3"],
         [1, 1, 1, 1]),
        ("uneven-groups", ["ground", "sky", "castle"], [3, 1, 5]),
        ("smb-sized", ["palette_0", "palette_1", "palette_2", "palette_3"],
         [16, 24, 32, 29]),
    ]
    for name, names, sizes in layouts:
        total = sum(sizes)
        payload = lcg(total, total * 4)
        parameters = {
            "group_names": names,
            "group_sizes": sizes,
            "tile_base": 0x100,
        }
        decoded = decode_metatiles(payload, parameters)
        if encode_metatiles(decoded, parameters) != payload:
            raise SystemExit(f"metatile case {name} does not round-trip")
        records = [value for record in decoded["records"] for value in record]
        cases.append((name, records, payload))
    return cases


def render() -> str:
    lines = [
        f"schema {SCHEMA}",
        f"schema_version {SCHEMA_VERSION}",
        "generator retrolarium_kit.nes_resources",
    ]
    for name, payload in payload_cases():
        tiles = decode_chr_2bpp(payload)
        # Re-encoding has to give the original bytes back, or the corpus would
        # be pinning a decoder that quietly loses information.
        if encode_chr_2bpp(tiles, len(tiles)) != payload:
            raise SystemExit(f"case {name} does not round-trip through the oracle")
        lines.append(f"case {name}")
        lines.append(f"payload {payload.hex()}")
        lines.append(f"tiles {len(tiles)}")
        lines.append(f"pixels {flatten(tiles)}")
        lines.append("end")
    for name, records, payload in metatile_cases():
        lines.append(f"metatile-case {name}")
        lines.append(f"payload {payload.hex()}")
        lines.append(f"records {len(records) // 4}")
        lines.append(f"values {' '.join(str(value) for value in records)}")
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
    print(f"{output}: {len(payload_cases())} tile cases, {len(metatile_cases())} metatile cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
