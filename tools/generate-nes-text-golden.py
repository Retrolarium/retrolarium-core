#!/usr/bin/env python3
"""Emit the fixed-width text parity corpus from the Python oracle.

The core treats an encoding's characters as single bytes, which is what every
NES font in the profiles uses. A multi-byte character would map per byte and
diverge, so this refuses to emit a non-ASCII encoding rather than letting that
pass unnoticed.

Usage:
    python tools/generate-nes-text-golden.py <output.txt> [--check]
"""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "retrolarium-kit" / "src"))

from retrolarium_kit.platform.nes.text import (  # noqa: E402
    NesTextError,
    TextEncoding,
    decode_text,
    encode_text,
)

SCHEMA = "retrolarium.nes-text-golden"
SCHEMA_VERSION = 1

# An SMB-shaped table: space as padding, then digits and letters.
CHARACTERS = " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-x"
CODES = tuple(range(0x24, 0x24 + len(CHARACTERS)))
PADDING = CODES[0]

UPPER = TextEncoding(CHARACTERS, CODES, "upper", PADDING)
NONE = TextEncoding(CHARACTERS, CODES, "", PADDING)
LOWER_CHARACTERS = " abcdefghijklmnopqrstuvwxyz0123456789"
LOWER = TextEncoding(
    LOWER_CHARACTERS, tuple(range(0x10, 0x10 + len(LOWER_CHARACTERS))), "lower", 0x10
)

ENCODINGS = {"upper": UPPER, "none": NONE, "lower": LOWER}


def encode_cases() -> list[tuple[str, str, str, int]]:
    """(name, encoding key, text, field width)."""
    return [
        ("plain", "upper", "HELLO", 8),
        ("exact-width", "upper", "WORLD 1-1", 9),
        ("empty", "upper", "", 6),
        ("case-folded-up", "upper", "hello", 8),
        ("case-folded-down", "lower", "HELLO", 8),
        ("no-folding", "none", "ABC", 5),
        ("digits", "upper", "000000", 6),
        ("hyphen", "upper", "1-2", 4),
        ("single-char", "upper", "X", 1),
    ]


def rejection_cases() -> list[tuple[str, str, str, int]]:
    return [
        ("too-long", "upper", "SUPERLONG", 4),
        ("unsupported-character", "upper", "HELLO!", 8),
        # Folding happens first, so a lowercase letter absent from an
        # unfolded table is still rejected.
        ("unfolded-lowercase", "none", "hello", 8),
    ]


def render() -> str:
    for key, encoding in ENCODINGS.items():
        if not encoding.characters.isascii():
            raise SystemExit(
                f"encoding {key} is not ASCII; the core maps characters per byte"
            )

    lines = [
        f"schema {SCHEMA}",
        f"schema_version {SCHEMA_VERSION}",
        "generator retrolarium_kit.platform.nes.text",
    ]
    for key, encoding in ENCODINGS.items():
        lines.append(f"encoding {key}")
        lines.append(f"characters {encoding.characters}")
        lines.append("codes " + ",".join(str(code) for code in encoding.codes))
        lines.append(f"case-fold {encoding.case_fold or '-'}")
        lines.append(f"padding {encoding.padding}")
        lines.append("end")

    for name, key, text, width in encode_cases():
        encoding = ENCODINGS[key]
        payload = encode_text(text, width, encoding, name)
        restored = decode_text(payload, encoding, name)
        lines.append(f"case {name}")
        lines.append(f"encoding-key {key}")
        lines.append(f"text {text}")
        lines.append(f"width {width}")
        lines.append(f"payload {payload.hex()}")
        lines.append(f"decoded {restored}")
        lines.append("end")

    for name, key, text, width in rejection_cases():
        try:
            encode_text(text, width, ENCODINGS[key], name)
        except NesTextError:
            pass
        else:
            raise SystemExit(f"rejection case {name} unexpectedly encoded")
        lines.append(f"reject-case {name}")
        lines.append(f"encoding-key {key}")
        lines.append(f"text {text}")
        lines.append(f"width {width}")
        lines.append("end")

    # An unmapped glyph has to be refused on the way in as well.
    unmapped = bytes([0xFE, PADDING])
    try:
        decode_text(unmapped, UPPER, "unmapped")
    except NesTextError:
        pass
    else:
        raise SystemExit("an unmapped glyph was decoded")
    lines.append("reject-decode unmapped")
    lines.append("encoding-key upper")
    lines.append(f"payload {unmapped.hex()}")
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
    print(f"{output}: {len(encode_cases())} cases, "
          f"{len(rejection_cases()) + 1} rejections")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
