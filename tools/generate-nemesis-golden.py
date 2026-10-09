#!/usr/bin/env python3
"""Emit the Nemesis decode parity corpus from the Python oracle.

The Nemesis compressor in the wild is really a *re*-compressor: it lifts the
code table out of an existing stream rather than inventing one, so it cannot
produce a test input from nothing. This builds valid streams directly instead,
which also keeps ROM bytes out of the repository.

The builder below is deliberately simple and is test-only - it exists to
produce well-formed input, not to compress well. Expected output always comes
from ``retrolarium_core.oracles.nemesis``.

Usage:
    python tools/generate-nemesis-golden.py <output.txt> [--check]
"""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "retrolarium-kit" / "src"))
sys.path.insert(0, str(REPO_ROOT / "retrolarium-core" / "python"))

from retrolarium_core.oracles.nemesis import decompress  # noqa: E402
from retrolarium_core.oracles.nemesis_encode import compress  # noqa: E402

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


def encode_cases() -> list[dict]:
    """Re-encoding pins: same plain data, same reference, same output bytes.

    Nemesis cannot compress without a reference, so each case supplies one and
    the encoder reuses its header and code table.
    """

    result = []

    def case(name: str, reference: bytes, mutate=None) -> None:
        plain = bytearray(decompress(reference))
        if mutate is not None:
            mutate(plain)
        encoded = compress(bytes(plain), reference)
        if decompress(encoded) != bytes(plain):
            raise SystemExit(f"encode case {name} does not round-trip")
        result.append({
            "name": name,
            "plain": bytes(plain),
            "reference": reference,
            "expect": encoded,
        })

    flat = build_stream(1, False, [(5, 8)] * 8)
    mixed = build_stream(1, False, [(1, 4), (2, 4), (3, 8), (4, 8),
                                    (1, 8), (2, 8), (3, 8), (4, 8),
                                    (5, 4), (5, 4)])
    xor = build_stream(1, True, [(3, 8), (12, 8)] * 4)
    two = build_stream(2, False, [(1, 8), (2, 8)] * 8)

    # Unchanged content: the encoder still re-encodes rather than echoing.
    case("unchanged-flat", flat)
    case("unchanged-mixed", mixed)
    case("unchanged-xor", xor)
    case("unchanged-two-tiles", two)

    # Edited content, which is what forces a genuine re-encode.
    def touch_first(buffer: bytearray) -> None:
        buffer[0] ^= 0xF0

    def touch_last(buffer: bytearray) -> None:
        buffer[-1] ^= 0x0F

    def scramble(buffer: bytearray) -> None:
        for index in range(0, len(buffer), 3):
            buffer[index] = (buffer[index] + 0x11) & 0xFF

    case("edited-flat", flat, touch_first)
    case("edited-mixed", mixed, touch_last)
    case("edited-xor", xor, touch_first)
    case("scrambled-two-tiles", two, scramble)

    # Content the reference's table cannot describe, forcing inline runs.
    def unknown_nybbles(buffer: bytearray) -> None:
        for index in range(len(buffer)):
            buffer[index] = 0xAB

    case("forces-inline-runs", flat, unknown_nybbles)

    return result


def render() -> str:
    lines = [
        f"schema {SCHEMA}",
        f"schema_version {SCHEMA_VERSION}",
        "generator retrolarium_core.oracles.nemesis",
    ]
    for entry in cases():
        lines.append(f"case {entry['name']}")
        lines.append(f"stream {entry['stream'].hex()}")
        lines.append(f"expect {entry['expect'].hex()}")
        lines.append("end")
    for entry in encode_cases():
        lines.append(f"encode-case {entry['name']}")
        lines.append(f"plain {entry['plain'].hex()}")
        lines.append(f"reference {entry['reference'].hex()}")
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
    print(f"{output}: {len(cases())} decode cases, {len(encode_cases())} encode cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
