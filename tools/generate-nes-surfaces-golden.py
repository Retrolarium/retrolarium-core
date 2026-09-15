#!/usr/bin/env python3
"""Emit the NES palette and nametable parity corpus from the Python oracle.

Unlike CHR, neither format has a standalone function in the Kit: the logic sits
inside ``decode_resources`` and ``build_resources``, reached through a profile.
So this builds a real profile over a synthetic image and drives those, rather
than restating the rules here. An oracle you paraphrase is not an oracle.

Usage:
    python retrolarium_core/tools/generate-nes-surfaces-golden.py <output.txt> [--check]
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "retrolarium_kit" / "src"))

from retrolarium_kit.authoring import (  # noqa: E402
    GameProfile,
    ResourceSpec,
    RevisionSpec,
)
from retrolarium_kit.nes_resources import (  # noqa: E402
    build_resources,
    decode_resources,
    parse_resource_document,
)

SCHEMA = "retrolarium.nes-surfaces-golden"
SCHEMA_VERSION = 1

PRG_SIZE = 0x4000
CHR_SIZE = 0x2000

# Layout inside PRG, chosen so the regions do not touch each other.
PALETTE_OFFSET = 0x10
PALETTE_ENTRIES = 8
NAMETABLE_OFFSET = 0x30
NAMETABLE_WIDTH = 4
NAMETABLE_HEIGHT = 3
NAMETABLE_ATTRIBUTES = 5
# One logical colour stored in three separate places, as a game does when the
# same value is embedded in several PPU commands.
REPLICATED_OFFSETS = ((0x60, 0x70, 0x80), (0x61, 0x71), (0x62,), (0x63, 0x90))


def build_image() -> bytes:
    header = b"NES\x1a" + bytes((1, 1, 0, 0)) + bytes(8)
    prg = bytearray(PRG_SIZE)

    palette = bytes((0x0F, 0x30, 0x21, 0x02, 0x3F, 0x00, 0x16, 0x27))
    prg[PALETTE_OFFSET:PALETTE_OFFSET + len(palette)] = palette

    cells = NAMETABLE_WIDTH * NAMETABLE_HEIGHT
    nametable = bytes((index * 7 + 1) & 0xFF for index in range(cells))
    attributes = bytes((0x00, 0x55, 0xAA, 0xFF, 0x1B))
    prg[NAMETABLE_OFFSET:NAMETABLE_OFFSET + cells + len(attributes)] = (
        nametable + attributes
    )

    for entry, offsets in enumerate(REPLICATED_OFFSETS):
        value = (entry * 9 + 3) & 0x3F
        for offset in offsets:
            prg[offset] = value

    return header + bytes(prg) + bytes(CHR_SIZE)


def build_profile(image: bytes) -> tuple[GameProfile, RevisionSpec]:
    revision = RevisionSpec(
        "probe-v1",
        "NES surface probe",
        len(image),
        hashlib.sha1(image).hexdigest(),
        hashlib.sha256(image).hexdigest(),
        "ines",
        0,
    )
    # File offsets include the 16-byte iNES header.
    base = 16
    resources = (
        ResourceSpec(
            "authoring-bundle", "resource-bundle", "nes.resource-bundle.v1", "fixed"
        ),
        ResourceSpec(
            "palette", "palette", "nes.palette-table.v1", "fixed",
            {
                "file_offset": base + PALETTE_OFFSET,
                "size": PALETTE_ENTRIES,
                "entries": PALETTE_ENTRIES,
            },
        ),
        ResourceSpec(
            "replicated-palette", "palette", "nes.palette-table.v1", "fixed",
            {
                "entries": len(REPLICATED_OFFSETS),
                "replicated_file_offsets": [
                    [base + offset for offset in offsets]
                    for offsets in REPLICATED_OFFSETS
                ],
            },
        ),
        ResourceSpec(
            "screen", "screen", "nes.nametable.v1", "fixed",
            {
                "file_offset": base + NAMETABLE_OFFSET,
                "size": NAMETABLE_WIDTH * NAMETABLE_HEIGHT + NAMETABLE_ATTRIBUTES,
                "width": NAMETABLE_WIDTH,
                "height": NAMETABLE_HEIGHT,
                "attribute_bytes": NAMETABLE_ATTRIBUTES,
            },
        ),
    )
    return (
        GameProfile(
            "nes-surface-probe", 1, "NES surface probe", "nes",
            ("screens", "palettes"), (revision,), resources,
        ),
        revision,
    )


def resource(document, identifier: str) -> dict:
    for item in document["resources"]:
        if item["id"] == identifier:
            return item
    raise SystemExit(f"resource {identifier} is missing from the decoded document")


def render() -> str:
    image = build_image()
    profile, revision = build_profile(image)
    document = decode_resources(image, profile, revision).as_dict()

    palette = resource(document, "palette")
    replicated = resource(document, "replicated-palette")
    screen = resource(document, "screen")

    base = 16
    palette_payload = image[base + PALETTE_OFFSET:
                            base + PALETTE_OFFSET + PALETTE_ENTRIES]
    cells = NAMETABLE_WIDTH * NAMETABLE_HEIGHT
    screen_payload = image[base + NAMETABLE_OFFSET:
                           base + NAMETABLE_OFFSET + cells + NAMETABLE_ATTRIBUTES]

    # An edit has to survive the round trip, so the corpus also pins what the
    # oracle writes back rather than only what it reads.
    edited = {
        "schema": document["schema"],
        "schema_version": document["schema_version"],
        "game": document["game"],
        "revision": document["revision"],
        "source_sha256": document["source_sha256"],
        "resources": [dict(item) for item in document["resources"]],
    }
    for item in edited["resources"]:
        if item["id"] == "palette":
            item["values"] = [(value + 1) & 0x3F for value in item["values"]]
        elif item["id"] == "replicated-palette":
            item["values"] = [(value + 5) & 0x3F for value in item["values"]]
        elif item["id"] == "screen":
            item["tiles"] = [[(cell + 3) & 0xFF for cell in row]
                             for row in item["tiles"]]
            item["attributes"] = [(value ^ 0x0F) for value in item["attributes"]]
    parsed = parse_resource_document(edited, profile, revision)
    rebuilt, _report = build_resources(image, parsed, profile, revision)

    edited_palette = next(i for i in edited["resources"] if i["id"] == "palette")
    edited_replicated = next(
        i for i in edited["resources"] if i["id"] == "replicated-palette")
    edited_screen = next(i for i in edited["resources"] if i["id"] == "screen")

    lines = [
        f"schema {SCHEMA}",
        f"schema_version {SCHEMA_VERSION}",
        "generator retrolarium_kit.nes_resources",
        "",
        "palette-case contiguous",
        f"payload {palette_payload.hex()}",
        f"values {' '.join(str(value) for value in palette['values'])}",
        f"edited-values {' '.join(str(v) for v in edited_palette['values'])}",
        "edited-payload " + bytes(
            rebuilt[base + PALETTE_OFFSET:
                    base + PALETTE_OFFSET + PALETTE_ENTRIES]).hex(),
        "end",
        "",
        "palette-case replicated",
        "offsets " + ";".join(
            ",".join(str(base + offset) for offset in offsets)
            for offsets in REPLICATED_OFFSETS),
        f"values {' '.join(str(value) for value in replicated['values'])}",
        f"edited-values {' '.join(str(v) for v in edited_replicated['values'])}",
        "edited-bytes " + ";".join(
            ",".join(str(rebuilt[base + offset]) for offset in offsets)
            for offsets in REPLICATED_OFFSETS),
        "end",
        "",
        "nametable-case grid",
        f"payload {screen_payload.hex()}",
        f"width {NAMETABLE_WIDTH}",
        f"height {NAMETABLE_HEIGHT}",
        f"attribute-count {NAMETABLE_ATTRIBUTES}",
        "tiles " + ";".join(
            ",".join(str(cell) for cell in row) for row in screen["tiles"]),
        f"attributes {' '.join(str(value) for value in screen['attributes'])}",
        "edited-tiles " + ";".join(
            ",".join(str(cell) for cell in row) for row in edited_screen["tiles"]),
        f"edited-attributes {' '.join(str(v) for v in edited_screen['attributes'])}",
        "edited-payload " + bytes(
            rebuilt[base + NAMETABLE_OFFSET:
                    base + NAMETABLE_OFFSET + cells + NAMETABLE_ATTRIBUTES]).hex(),
        "end",
    ]
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
    print(f"{output}: 3 cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
