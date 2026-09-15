#!/usr/bin/env python3
"""Emit the Nemesis decode parity corpus from the Python oracle.

The Nemesis compressor in the wild is really a *re*-compressor: it lifts the
code table out of an existing stream rather than inventing one, so it cannot
produce a test input from nothing. This builds valid streams directly instead,
which also keeps ROM bytes out of the repository.

The builder below is deliberately simple and is test-only - it exists to
produce well-formed input, not to compress well. Expected output always comes
from ``retrolarium_kit.oracles.nemesis``.

Usage:
    python retrolarium_core/tools/generate-nemesis-golden.py <output.txt> [--check]
"""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "retrolarium_kit" / "src"))

from retrolarium_kit.oracles.nemesis import decompress  # noqa: E402

SCHEMA = "retrolarium.nemesis-golden"
SCHEMA_VERSION = 1

# Prefix-free codes that avoid 0b111111, which the format reserves as the
# inline-run escape. (value, bit length) indexed by slot.
CODES: tuple[tuple[int, int], ...] = (
    (0b00, 2),
    (0b01, 2),
    (0b10, 2),
    (0b110, 3),
    (0b1110, 4),
    (0b11110, 5),
    (0b111110, 6),
)


class BitWriter:
    def __init__(self) -> None:
        self.bits: list[int] = []

    def write(self, value: int, count: int) -> None:
        for shift in range(count - 1, -1, -1):
            self.bits.append((value >> shift) & 1)

    def to_bytes(self) -> bytes:
        padded = self.bits + [0] * ((-len(self.bits)) % 8)
        out = bytearray()
        for index in range(0, len(padded), 8):
            byte = 0
            for bit in padded[index:index + 8]:
                byte = (byte << 1) | bit
            out.append(byte)
        # The reader keeps a two-byte window primed, so a stream that ends
        # exactly on a code boundary still needs bytes to shift in.
        out.extend(b"\x00\x00")
        return bytes(out)


def build_stream(tiles: int, xor_mode: bool,
                 runs: list[tuple[int, int]],
                 inline: set[int] | None = None) -> bytes:
    """Assemble a Nemesis stream emitting `runs` of (nybble, run_length).

    Entries whose index is in `inline` are written with the escape sequence
    instead of a table code, so both paths are exercised.
    """
    inline = inline or set()

    # Assign one code per distinct (nybble, run) pair, in first-use order.
    assignments: dict[tuple[int, int], tuple[int, int]] = {}
    for index, pair in enumerate(runs):
        if index in inline or pair in assignments:
            continue
        if len(assignments) >= len(CODES):
            raise SystemExit("too many distinct runs for the fixed code set")
        assignments[pair] = CODES[len(assignments)]

    header = (0x8000 if xor_mode else 0) | tiles
    out = bytearray([(header >> 8) & 0xFF, header & 0xFF])

    # Code table: a palette marker, then its entries, switching with 0x80|n.
    by_nybble: dict[int, list[tuple[int, int, int, int]]] = {}
    for (nybble, run), (code, bits) in assignments.items():
        by_nybble.setdefault(nybble, []).append((run, code, bits, nybble))

    first = True
    for nybble in sorted(by_nybble):
        out.append(nybble if first else 0x80 | nybble)
        first = False
        for run, code, bits, _ in sorted(by_nybble[nybble]):
            out.append(((run - 1) << 4) | (bits & 0x0F))
            out.append(code)
    out.append(0xFF)

    writer = BitWriter()
    for index, (nybble, run) in enumerate(runs):
        if index in inline:
            writer.write(0b111111, 6)
            writer.write(run - 1, 3)
            writer.write(nybble, 4)
        else:
            code, bits = assignments[(nybble, run)]
            writer.write(code, bits)
    out.extend(writer.to_bytes())
    return bytes(out)


def case(name: str, stream: bytes) -> dict:
    return {"name": name, "stream": stream, "expect": decompress(stream)}


def cases() -> list[dict]:
    result = []

    # One tile, a single nybble repeated: 64 nybbles in runs of 8.
    result.append(case("single-tile-flat",
        build_stream(1, False, [(5, 8)] * 8)))

    # One tile built from alternating nybbles and varied run lengths.
    runs = [(1, 4), (2, 4), (3, 8), (4, 8), (1, 8), (2, 8), (3, 8), (4, 8),
            (5, 4), (5, 4)]
    result.append(case("single-tile-mixed", build_stream(1, False, runs)))

    # The same content in XOR mode, where each group is xored with the last.
    result.append(case("xor-mode", build_stream(1, True, runs)))

    # Inline escapes instead of table codes for some runs.
    result.append(case("inline-runs",
        build_stream(1, False, [(7, 8)] * 8, inline={1, 3, 5})))

    # Every run inline: the code table holds nothing at all.
    result.append(case("all-inline",
        build_stream(1, False, [(9, 8)] * 8, inline=set(range(8)))))

    # Two tiles, so the decoder has to keep going past the first group.
    result.append(case("two-tiles",
        build_stream(2, False, [(1, 8), (2, 8)] * 8)))

    # Two tiles in XOR mode, where the chain crosses the tile boundary.
    result.append(case("two-tiles-xor",
        build_stream(2, True, [(3, 8), (12, 8)] * 8)))

    # A declared count of zero produces nothing, whatever follows.
    result.append(case("zero-tiles", build_stream(0, False, [(1, 8)])))

    return result


def render() -> str:
    lines = [
        f"schema {SCHEMA}",
        f"schema_version {SCHEMA_VERSION}",
        "generator retrolarium_kit.oracles.nemesis",
    ]
    for entry in cases():
        lines.append(f"case {entry['name']}")
        lines.append(f"stream {entry['stream'].hex()}")
        lines.append(f"expect {entry['expect'].hex()}")
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
    print(f"{output}: {len(cases())} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
