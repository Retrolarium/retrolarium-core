#!/usr/bin/env python3
"""Emit the resource-source corpus from the Python oracle.

This pins how a resource turns into bytes: which payload backs it, where its
spans sit, and what has to be refused. The oracle is the Kit's own private
helpers in retrolarium_kit.nes_resources - the real code, not a restatement of
its rules.

The ROM image is described rather than carried, the way the FDS corpus does
it, and both sides compare its SHA-256 before anything else.

Usage:
    python tools/generate-resource-source-golden.py <out.txt> [--check]
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "retrolarium-kit" / "src"))

from retrolarium_kit.core.authoring import AuthoringError  # noqa: E402
from retrolarium_kit.core.game_profiles import parse_game_profile  # noqa: E402
from retrolarium_kit.platform.nes.resources import (  # noqa: E402
    NesResourceError,
    _encoded_resource_spans,
    _read_resource_spans,
    _replicated_palette_offsets,
    _resource_source,
    _revision_image,
    _span,
    _ResourceSpan,
)

SCHEMA = "retrolarium.resource-source-golden"
SCHEMA_VERSION = 1

# A 32 KiB PRG behind a 16-byte iNES header, which is the smallest shape the
# packaged profiles use.
HEADER_SIZE = 16
PRG_SIZE = 32768
IMAGE_SIZE = HEADER_SIZE + PRG_SIZE


def build_image() -> bytes:
    """A deterministic iNES image: header, then a counting PRG."""
    image = bytearray(IMAGE_SIZE)
    image[0:4] = b"NES\x1a"
    image[4] = 2  # 2 x 16 KiB PRG
    image[5] = 0  # no CHR ROM
    image[6] = 0
    image[7] = 0
    for index in range(PRG_SIZE):
        image[HEADER_SIZE + index] = (index * 7 + 13) & 0xFF
    return bytes(image)


IMAGE = build_image()
PRG_SHA1 = hashlib.sha1(IMAGE[HEADER_SIZE:]).hexdigest()
IMAGE_SHA1 = hashlib.sha1(IMAGE).hexdigest()
IMAGE_SHA256 = hashlib.sha256(IMAGE).hexdigest()


def profile_document(*, payload_sha1: str = PRG_SHA1,
                     payload_size: int = PRG_SIZE,
                     payload_offset: int = HEADER_SIZE) -> dict:
    return {
        "schema": "retrolarium.game-profile",
        "schema_version": 1,
        "id": "spans",
        "profile_version": 1,
        "name": "Spans",
        "platform": "nes",
        "capabilities": [],
        "resources": [
            {
                "id": "in-payload",
                "kind": "graphics",
                "codec": "nes.chr-2bpp.v1",
                "capacity_policy": "fixed",
                "parameters": {"file_offset": 64, "size": 16},
                "payload": "prg",
            },
            {
                "id": "in-image",
                "kind": "graphics",
                "codec": "nes.chr-2bpp.v1",
                "capacity_policy": "fixed",
                "parameters": {"file_offset": 1024, "size": 16},
            },
            {
                "id": "replicated",
                "kind": "palette",
                "codec": "nes.palette-table.v1",
                "capacity_policy": "fixed",
                "parameters": {
                    "file_offset": 2048,
                    "size": 4,
                    "replicated_file_offsets": [[100, 200], [300], [400], [500]],
                },
            },
        ],
        "revisions": [
            {
                "id": "ines",
                "name": "iNES",
                "size": IMAGE_SIZE,
                "sha1": IMAGE_SHA1,
                "sha256": IMAGE_SHA256,
                "container": "ines",
                "mapper": 0,
                "payloads": [
                    {
                        "id": "prg",
                        "storage": "range",
                        "size": payload_size,
                        "sha1": payload_sha1,
                        "file_offset": payload_offset,
                        "load_address": 32768,
                    }
                ],
            }
        ],
    }


def load(document: dict):
    profile = parse_game_profile(document)
    return profile, profile.revisions[0]


def describe_spans(spans: tuple[_ResourceSpan, ...]) -> str:
    return ";".join(
        f"{span.offset},{span.size},{span.payload_id or ''}" for span in spans
    )


def cases() -> list[dict]:
    return [
        {
            "name": "payload-span",
            "resource": "in-payload",
            "spans": [(0, 16, "prg")],
        },
        {
            "name": "image-span",
            "resource": "in-image",
            "spans": [(1024, 16, None)],
        },
        {
            "name": "several-spans-one-payload",
            "resource": "in-payload",
            "spans": [(0, 8, "prg"), (256, 8, "prg"), (1024, 16, "prg")],
        },
        {
            "name": "mixed-sources",
            "resource": "in-image",
            "spans": [(0, 4, "prg"), (100, 4, None)],
        },
    ]


def rejections() -> list[dict]:
    return [
        {
            "name": "span-past-the-payload",
            "resource": "in-payload",
            "spans": [(PRG_SIZE - 4, 16, "prg")],
        },
        {
            "name": "unknown-payload",
            "resource": "in-payload",
            "spans": [(0, 4, "absent")],
        },
        {
            "name": "payload-sha1-differs",
            "resource": "in-payload",
            "spans": [(0, 4, "prg")],
            "profile": profile_document(payload_sha1="0" * 40),
        },
        {
            # The payload starts close enough to the end that the image cannot
            # supply the size it declares.
            "name": "payload-runs-past-the-image",
            "resource": "in-payload",
            "spans": [(0, 4, "prg")],
            "profile": profile_document(
                payload_offset=IMAGE_SIZE - 10, payload_size=100,
                payload_sha1="0" * 40),
        },
    ]


def render() -> str:
    lines = [
        f"schema {SCHEMA}",
        f"schema_version {SCHEMA_VERSION}",
        "generator retrolarium_kit.platform.nes.resources",
        f"image-sha256 {IMAGE_SHA256}",
        f"image-size {IMAGE_SIZE}",
        f"prg-offset {HEADER_SIZE}",
    ]

    base = profile_document()
    lines.append("profile " + json.dumps(base).encode("utf-8").hex())

    profile, revision = load(base)
    image = _revision_image(IMAGE, revision)
    lines.append(f"container-mapper {image.mapper}")

    for case in cases():
        resource = profile.resource(case["resource"], revision)
        spans = tuple(
            _ResourceSpan(offset, size, payload) for offset, size, payload in
            case["spans"]
        )
        read = _read_resource_spans(IMAGE, profile, revision, resource, spans)
        encoded = _encoded_resource_spans(read, spans)

        lines.append("case " + case["name"])
        lines.append("resource " + case["resource"])
        lines.append("spans " + describe_spans(spans))
        lines.append("read-sha256 " + hashlib.sha256(read).hexdigest())
        lines.append(f"read-size {len(read)}")
        lines.append("encoded " + ";".join(
            f"{item.offset},{len(item.replacement)},{item.payload_id or ''}"
            for item in encoded))
        lines.append("end")

    # The single span a fixed resource declares through its parameters.
    for resource_id, expected in (("in-payload", 16), ("in-image", 16)):
        resource = profile.resource(resource_id, revision)
        offset, size = _span(resource, expected)
        lines.append("parameter-span " + resource_id)
        lines.append(f"expected {expected}")
        lines.append(f"resolved {offset} {size}")
        lines.append("end")

    replicated = _replicated_palette_offsets(
        profile.resource("replicated", revision), 4)
    lines.append("replicated replicated")
    lines.append("entries 4")
    lines.append("offsets " + ";".join(
        ",".join(str(value) for value in entry) for entry in replicated))
    lines.append("end")

    # A resource with no payload reads the whole image.
    whole = _resource_source(
        IMAGE, profile, revision, profile.resource("in-image", revision))
    lines.append("resource-source in-image")
    lines.append("sha256 " + hashlib.sha256(whole).hexdigest())
    lines.append("end")

    for case in rejections():
        document = case.get("profile", base)
        candidate, candidate_revision = load(document)
        resource = candidate.resource(case["resource"], candidate_revision)
        spans = tuple(
            _ResourceSpan(offset, size, payload) for offset, size, payload in
            case["spans"]
        )
        try:
            _read_resource_spans(
                IMAGE, candidate, candidate_revision, resource, spans)
        except (NesResourceError, AuthoringError) as error:
            message = str(error)
        else:
            raise SystemExit(f"{case['name']} was read; a refusal is expected")
        lines.append("reject " + case["name"])
        if "profile" in case:
            lines.append("profile " + json.dumps(document).encode("utf-8").hex())
        lines.append("resource " + case["resource"])
        lines.append("spans " + describe_spans(spans))
        lines.append("message " + message.encode("utf-8").hex())
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
    print(f"{output}: {len(cases())} span layouts, {len(rejections())} refusals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
