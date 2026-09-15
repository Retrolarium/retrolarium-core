#!/usr/bin/env python3
"""Emit the Enigma decode parity corpus from the Python oracle.

Streams are assembled here rather than taken from a ROM. The builder is
test-only: it exists to produce well-formed input covering every reachable
code path, not to compress well. Expected output always comes from
``retrolarium_kit.oracles.enigma``.

Modes 2 and 3 are unreachable in this format as implemented - a six-bit code
is at most 0x1F after its shift, and a seven-bit code is at least 0x40 - so no
case can exercise them. That is verified here rather than assumed.

Usage:
    python retrolarium_core/tools/generate-enigma-golden.py <output.txt> [--check]
"""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "retrolarium_kit" / "src"))

from retrolarium_kit.oracles.enigma import decompress  # noqa: E402
from retrolarium_kit.oracles.enigma_encode import encode  # noqa: E402

SCHEMA = "retrolarium.enigma-golden"
SCHEMA_VERSION = 1

# flags_byte values selecting which per-tile flip bits the stream carries.
NO_FLAGS = 0x00
VFLIP_ONLY = 0x01
HFLIP_ONLY = 0x02
BOTH_FLIPS = 0xFF


def reachable_modes() -> set[int]:
    modes = set()
    for code in range(0x80):
        repeat = code >> 1 if code < 0x40 else code
        modes.add((repeat >> 4) & 7)
    return modes


class BitWriter:
    def __init__(self) -> None:
        self.bits: list[int] = []

    def write(self, value: int, count: int) -> None:
        for shift in range(count - 1, -1, -1):
            self.bits.append((value >> shift) & 1)

    def code(self, mode: int, repeat: int) -> None:
        """Write one command. Six bits for modes 0-1, seven for 4-7."""
        value = ((mode & 7) << 4) | (repeat & 0x0F)
        if mode < 2:
            # Must stay under 0x20 so the reader's seven-bit peek lands below
            # 0x40 and it hands the spare bit back.
            assert value < 0x20, f"mode {mode} repeat {repeat} is not a six-bit code"
            self.write(value, 6)
        else:
            assert 0x40 <= value <= 0x7F, f"mode {mode} is not a seven-bit code"
            self.write(value, 7)

    def to_bytes(self) -> bytes:
        padded = self.bits + [0] * ((-len(self.bits)) % 8)
        out = bytearray()
        for index in range(0, len(padded), 8):
            byte = 0
            for bit in padded[index:index + 8]:
                byte = (byte << 1) | bit
            out.append(byte)
        # The reader primes a two-byte window, so leave bytes to shift in.
        out.extend(b"\x00\x00")
        return bytes(out)


def build(bits_count: int, flags_byte: int, inc_tile: int, static_tile: int,
          program) -> bytes:
    writer = BitWriter()
    program(writer, bits_count, flags_byte)
    writer.code(7, 0x0F)  # terminator
    head = bytes([
        bits_count & 0xFF,
        flags_byte & 0xFF,
        (inc_tile >> 8) & 0xFF, inc_tile & 0xFF,
        (static_tile >> 8) & 0xFF, static_tile & 0xFF,
    ])
    return head + writer.to_bytes()


def tile_payload(writer: BitWriter, bits_count: int, flags_byte: int,
                 vflip: bool, hflip: bool, value: int) -> None:
    """Write the per-tile bits a decode_tile call will consume, in order."""
    flags = flags_byte if flags_byte < 0x80 else flags_byte - 0x100
    flags &= 0xFFFFFFFF
    flags = ((flags >> 1) | ((flags & 1) << 31)) & 0xFFFFFFFF
    low = ((flags & 0xFFFF) >> 1) | ((flags & 1) << 15)
    flags = (flags & 0xFFFF0000) | (low & 0xFFFF)

    if flags & 0x80000000:
        writer.write(1 if vflip else 0, 1)
    if flags & 0x8000:
        writer.write(1 if hflip else 0, 1)
    bits = abs(bits_count)
    if bits:
        writer.write(value, bits)


def cases() -> list[dict]:
    result: list[dict] = []

    def case(name: str, stream: bytes, base_tile: int = 0) -> None:
        result.append({
            "name": name,
            "base_tile": base_tile,
            "stream": stream,
            "expect": decompress(stream, base_tile),
        })

    # Mode 0/1: a run counted up from inc_tile.
    case("incrementing-run", build(0, NO_FLAGS, 0x0100, 0x0200,
        lambda w, b, f: w.code(0, 7)))
    case("incrementing-run-mode1", build(0, NO_FLAGS, 0x0100, 0x0200,
        lambda w, b, f: w.code(1, 3)))

    # Mode 4: one decoded tile repeated.
    case("repeat-decoded", build(4, NO_FLAGS, 0, 0x0200,
        lambda w, b, f: (w.code(4, 5), tile_payload(w, b, f, False, False, 9))))

    # Mode 5 and 6: decoded tile counted up and down.
    case("decoded-ascending", build(4, NO_FLAGS, 0, 0,
        lambda w, b, f: (w.code(5, 4), tile_payload(w, b, f, False, False, 3))))
    case("decoded-descending", build(4, NO_FLAGS, 0, 0,
        lambda w, b, f: (w.code(6, 4), tile_payload(w, b, f, False, False, 1))))

    # Mode 7: a run of individually decoded tiles.
    def inline_run(w, b, f):
        w.code(7, 3)
        for value in (1, 2, 3, 4):
            tile_payload(w, b, f, False, False, value)
    case("inline-tiles", build(5, NO_FLAGS, 0, 0, inline_run))

    # Per-tile flip bits, one flag at a time and then both.
    case("vflip-only", build(4, VFLIP_ONLY, 0, 0,
        lambda w, b, f: (w.code(4, 1), tile_payload(w, b, f, True, False, 6))))
    case("hflip-only", build(4, HFLIP_ONLY, 0, 0,
        lambda w, b, f: (w.code(4, 1), tile_payload(w, b, f, False, True, 6))))
    case("both-flips", build(4, BOTH_FLIPS, 0, 0,
        lambda w, b, f: (w.code(4, 1), tile_payload(w, b, f, True, True, 6))))

    # A negative bit count is taken as its absolute value.
    case("negative-bit-count", build(-4 & 0xFF, NO_FLAGS, 0, 0,
        lambda w, b, f: (w.code(4, 2), tile_payload(w, -4, f, False, False, 7))))

    # Zero bit count: decode_tile returns before reading any value bits.
    case("zero-bit-count", build(0, NO_FLAGS, 0, 0,
        lambda w, b, f: (w.code(4, 2), tile_payload(w, 0, f, False, False, 0))))

    # base_tile shifts every tile the stream produces.
    case("base-tile-offset", build(4, NO_FLAGS, 0x0010, 0x0020,
        lambda w, b, f: (w.code(0, 2), w.code(4, 1),
                         tile_payload(w, b, f, False, False, 5))),
        base_tile=0x0300)

    # Several commands in one stream, then the terminator.
    def mixed(w, b, f):
        w.code(0, 2)
        w.code(4, 1)
        tile_payload(w, b, f, False, False, 2)
        w.code(5, 2)
        tile_payload(w, b, f, False, False, 8)
        w.code(1, 1)
    case("mixed-commands", build(4, NO_FLAGS, 0x0400, 0x0500, mixed))

    # An immediate terminator produces nothing.
    case("empty", build(0, NO_FLAGS, 0, 0, lambda w, b, f: None))

    return result


def tilemap(words: list[int]) -> bytes:
    out = bytearray()
    for word in words:
        out.append((word >> 8) & 0xFF)
        out.append(word & 0xFF)
    return bytes(out)


def encode_cases() -> list[dict]:
    """Inputs whose compressed form both encoders must agree on byte for byte."""

    maps: list[tuple[str, list[int]]] = [
        ("ascending", list(range(0x100, 0x110))),
        ("repeated", [0x0042] * 12),
        ("descending", list(range(0x0210, 0x0200, -1))),
        ("two-runs", list(range(0x10, 0x18)) + [0x0077] * 8),
        ("literals", [3, 9, 1, 250, 17, 4, 88, 2]),
        ("single-word", [0x0001]),
        ("zero-word", [0x0000, 0x0000]),
        ("long-run", list(range(0x0300, 0x0330))),
        ("tie-heavy", [5, 5, 6, 6, 7, 7, 5, 5, 6, 6, 7, 7]),
        ("wide-words", [0x7FFF, 0x7FFE, 0x0001, 0x7FFF]),
    ]
    result = []
    for name, words in maps:
        plain = tilemap(words)
        compressed = encode(plain)
        # The corpus is only meaningful if the stream it pins actually decodes
        # back to its input, so the oracle checks itself here.
        if decompress(compressed) != plain:
            raise SystemExit(f"encode case {name} does not round-trip")
        result.append({"name": name, "plain": plain, "expect": compressed})
    return result


def render() -> str:
    unreachable = sorted(set(range(8)) - reachable_modes())
    lines = [
        f"schema {SCHEMA}",
        f"schema_version {SCHEMA_VERSION}",
        "generator retrolarium_kit.oracles.enigma",
        f"unreachable_modes {','.join(str(mode) for mode in unreachable)}",
    ]
    for entry in cases():
        lines.append(f"case {entry['name']}")
        lines.append(f"base_tile {entry['base_tile']}")
        lines.append(f"stream {entry['stream'].hex()}")
        lines.append(f"expect {entry['expect'].hex()}")
        lines.append("end")
    for entry in encode_cases():
        lines.append(f"encode-case {entry['name']}")
        lines.append(f"plain {entry['plain'].hex()}")
        lines.append(f"expect {entry['expect'].hex()}")
        lines.append("end")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if reachable_modes() != {0, 1, 4, 5, 6, 7}:
        print("mode reachability changed; revisit the corpus", file=sys.stderr)
        return 1

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
