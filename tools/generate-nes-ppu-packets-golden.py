#!/usr/bin/env python3
"""Emit the PPU display-list parity corpus from the Python oracle.

Only the byte grammar is ported to the core: the command header, the repeat and
vertical flags, the terminator, and the trailing padding that has to survive a
round trip. Projecting commands onto editable tile grids is presentation and
stays where it is for now.

``_decode_commands`` is private to the Kit module, and it is used here on
purpose: it is the oracle, and reaching for a public wrapper would drag in
profile plumbing this corpus does not need.

Usage:
    python tools/generate-nes-ppu-packets-golden.py <output.txt> [--check]
"""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "retrolarium-kit" / "src"))

from retrolarium_kit.platform.nes.screen_packets import (  # noqa: E402
    NesScreenPacketError,
    _decode_commands,
)

SCHEMA = "retrolarium.nes-ppu-packets-golden"
SCHEMA_VERSION = 1

TERMINATOR = 0x00


def command(address: int, values: list[int], *, vertical: bool = False,
            repeat: bool = False, length: int | None = None) -> bytes:
    if length is None:
        length = 1 if repeat else len(values)
    control = (0x80 if vertical else 0) | (0x40 if repeat else 0) | length
    return bytes([(address >> 8) & 0xFF, address & 0xFF, control, *values])


def packet(*parts: bytes, trailing: bytes = b"") -> bytes:
    return b"".join(parts) + bytes([TERMINATOR]) + trailing


def cases() -> list[tuple[str, bytes]]:
    return [
        # Nothing but the terminator.
        ("empty", packet()),

        # One horizontal write.
        ("single-horizontal", packet(command(0x2000, [1, 2, 3, 4]))),

        # Vertical, which only differs in the control bit.
        ("vertical", packet(command(0x23C0, [9, 9], vertical=True))),

        # A repeat carries one value but claims a longer run.
        ("repeat", packet(command(0x2100, [0x55], repeat=True, length=16))),

        # Repeat and vertical together, so neither flag masks the other.
        ("repeat-vertical", packet(
            command(0x2200, [0xAA], repeat=True, vertical=True, length=8))),

        # Several commands in sequence.
        ("sequence", packet(
            command(0x2000, [1, 2]),
            command(0x2040, [3], repeat=True, length=5),
            command(0x23C0, [0xFF, 0x0F], vertical=True))),

        # Trailing padding after the terminator must survive untouched.
        ("trailing-padding", packet(
            command(0x2000, [7, 7, 7]), trailing=bytes([0xDE, 0xAD, 0xBE, 0xEF]))),

        # The extremes of the address range and of the length field.
        ("address-low", packet(command(0x2000, [1]))),
        ("address-high", packet(command(0x3FFF, [1]))),
        ("length-one", packet(command(0x2500, [0x42]))),
        ("length-max", packet(command(0x2600, list(range(0x3F))))),
    ]


def rejection_cases() -> list[tuple[str, bytes]]:
    """Payloads both implementations must refuse."""
    return [
        ("no-terminator", command(0x2000, [1, 2])),
        ("truncated-header", bytes([0x20, 0x00])),
        ("truncated-values", bytes([0x20, 0x00, 0x04, 1, 2])),
        ("zero-length", bytes([0x20, 0x00, 0x00, 1, TERMINATOR])),
        ("address-below-ppu", bytes([0x1F, 0xFF, 0x01, 1, TERMINATOR])),
    ]


def describe(commands: list[dict]) -> str:
    parts = []
    for item in commands:
        values = ",".join(str(value) for value in item["values"])
        parts.append("{}:{}:{}:{}:{}".format(
            item["address"],
            1 if item["vertical"] else 0,
            1 if item["repeat"] else 0,
            item["length"],
            values,
        ))
    return ";".join(parts)


def render() -> str:
    lines = [
        f"schema {SCHEMA}",
        f"schema_version {SCHEMA_VERSION}",
        "generator retrolarium_kit.platform.nes.screen_packets",
        f"terminator {TERMINATOR}",
    ]
    for name, payload in cases():
        decoded = _decode_commands(payload, TERMINATOR, name)
        lines.append(f"case {name}")
        lines.append(f"payload {payload.hex()}")
        lines.append(f"commands {describe(decoded['commands'])}")
        lines.append("trailing " + ",".join(
            str(value) for value in decoded["trailing"]))
        lines.append("end")

    for name, payload in rejection_cases():
        try:
            _decode_commands(payload, TERMINATOR, name)
        except NesScreenPacketError:
            pass
        else:
            raise SystemExit(f"rejection case {name} unexpectedly decoded")
        lines.append(f"reject-case {name}")
        lines.append(f"payload {payload.hex()}")
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
    print(f"{output}: {len(cases())} cases, {len(rejection_cases())} rejections")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
