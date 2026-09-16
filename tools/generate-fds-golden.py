#!/usr/bin/env python3
"""Emit the FDS side corpus from the Python oracle.

A raw side is 65500 bytes, so the corpus describes one instead of carrying it:
a list of files, each with an id, a size and the byte it is filled with. Both
sides build the image from that description and record its SHA-256, so a
builder that drifted is caught before anything is compared.

Usage:
    python retrolarium_core/tools/generate-fds-golden.py <output.txt> [--check]
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "retrolarium_kit" / "src"))

from retrolarium_kit.fds import (  # noqa: E402
    FdsError,
    fds_payload,
    fds_payload_ranges,
    parse_fds_side,
    replace_fds_payload,
)

SCHEMA = "retrolarium.fds-golden"
SCHEMA_VERSION = 1

SIDE_SIZE = 65_500


def build_side(files: list[tuple[int, int, int]], *, corrupt: str = "") -> bytes:
    """Assemble one raw side from (file_id, size, fill) triples.

    `corrupt` names a single deliberate defect, so the refusal cases differ
    from the accepted ones by exactly one byte-level decision.
    """
    image = bytearray(SIDE_SIZE)
    image[0] = 1 if corrupt != "block1" else 9
    # Bytes 1..55 are the disk header; the parser does not read them, so they
    # carry a recognisable filler rather than zeros.
    for index in range(1, 56):
        image[index] = 0x5A
    image[56] = 2 if corrupt != "block2" else 9
    image[57] = len(files) if corrupt != "file-count" else len(files) + 1

    position = 58
    for number, (file_id, size, fill) in enumerate(files):
        header = bytearray(16)
        header[0] = 3 if corrupt != "block3" else 9
        header[1] = number
        header[2] = file_id
        header[3:11] = bytes(f"FILE{number:04d}", "ascii")
        header[11] = 0x00
        header[12] = 0x60
        header[13] = size & 0xFF
        header[14] = (size >> 8) & 0xFF
        if corrupt == "oversize" and number == 0:
            header[13] = 0xFF
            header[14] = 0xFF
        header[15] = 1
        image[position:position + 16] = header
        position += 16
        image[position] = 4 if corrupt != "block4" else 9
        position += 1
        # "oversize" only overstates the size in the header: the data written
        # is unchanged, so the parser fails on a data block that runs past the
        # end of the side rather than on a malformed image.
        image[position:position + size] = bytes([fill]) * size
        position += size

    if corrupt == "trailing":
        image[SIDE_SIZE - 1] = 0xFF
    return bytes(image[:SIDE_SIZE])


def describe_files(files: list[tuple[int, int, int]]) -> str:
    return ";".join(f"{file_id}:{size}:{fill}" for file_id, size, fill in files)


def cases() -> list[dict]:
    result = []

    # Two files, a payload spanning both, and a range that starts inside the
    # first and ends inside the second.
    files = [(0x10, 256, 0xAA), (0x11, 512, 0xBB)]
    result.append({
        "name": "two-files",
        "files": files,
        "select": [0x10, 0x11],
        "range": (200, 200),
    })

    # One file, and a range that covers all of it.
    files = [(0x20, 128, 0xCC)]
    result.append({
        "name": "single-file",
        "files": files,
        "select": [0x20],
        "range": (0, 128),
    })

    # Selection order decides the payload order, not the order on the side.
    files = [(0x30, 64, 0x01), (0x31, 64, 0x02), (0x32, 64, 0x03)]
    result.append({
        "name": "reordered-selection",
        "files": files,
        "select": [0x32, 0x30],
        "range": (32, 64),
    })

    return result


def rejections() -> list[dict]:
    files = [(0x10, 256, 0xAA), (0x11, 512, 0xBB)]
    result = [
        {"name": "block1", "files": files, "corrupt": "block1"},
        {"name": "block2", "files": files, "corrupt": "block2"},
        {"name": "block3", "files": files, "corrupt": "block3"},
        {"name": "block4", "files": files, "corrupt": "block4"},
        {"name": "file-count", "files": files, "corrupt": "file-count"},
        {"name": "oversize", "files": files, "corrupt": "oversize"},
        {"name": "trailing", "files": files, "corrupt": "trailing"},
    ]
    return result


def render() -> str:
    lines = [
        f"schema {SCHEMA}",
        f"schema_version {SCHEMA_VERSION}",
        "generator retrolarium_kit.fds",
    ]

    for case in cases():
        image = build_side(case["files"])
        records = parse_fds_side(image)
        payload = fds_payload(image, case["select"])
        offset, size = case["range"]
        ranges = fds_payload_ranges(image, case["select"], offset, size)
        replaced = replace_fds_payload(
            image, case["select"], bytes(len(payload)))

        lines.append("case " + case["name"])
        lines.append("files " + describe_files(case["files"]))
        lines.append("side-sha256 " + hashlib.sha256(image).hexdigest())
        lines.append("records " + ";".join(
            "{},{},{},{},{},{},{}".format(
                record.file_number, record.file_id, record.load_address,
                record.size, record.file_type, record.header_offset,
                record.data_offset)
            for record in records))
        lines.append("names " + ";".join(record.name.hex() for record in records))
        lines.append("select " + ",".join(str(item) for item in case["select"]))
        lines.append("payload-sha256 " + hashlib.sha256(payload).hexdigest())
        lines.append(f"payload-size {len(payload)}")
        lines.append(f"range-request {offset} {size}")
        lines.append("ranges " + ";".join(
            f"{item.file_offset},{item.payload_offset},{item.size}"
            for item in ranges))
        # Replacing with zeros is the strongest simple check: every selected
        # byte has to move, and nothing else may.
        lines.append("replaced-sha256 " + hashlib.sha256(replaced).hexdigest())
        lines.append("end")

    for case in rejections():
        image = build_side(case["files"], corrupt=case["corrupt"])
        try:
            parse_fds_side(image)
        except FdsError as error:
            message = str(error)
        else:
            raise SystemExit(f"{case['name']} parsed; the corpus expects a refusal")
        lines.append("reject " + case["name"])
        lines.append("files " + describe_files(case["files"]))
        lines.append("corrupt " + case["corrupt"])
        lines.append("side-sha256 " + hashlib.sha256(image).hexdigest())
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
    print(f"{output}: {len(cases())} sides, {len(rejections())} refusals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
