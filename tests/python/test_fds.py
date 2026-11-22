"""A raw Famicom Disk System side: blocks, files and payload ranges."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))

from retrolarium_core.fds import FdsError, inspect_fds_side, parse_fds_side  # noqa: E402

SIDE_SIZE = 65_500


def side(files: list[tuple[int, bytes]], tail: bytes = b"") -> bytes:
    """A side holding (file ID, data) files, then `tail` after the last one."""
    image = bytearray(SIDE_SIZE)
    image[0] = 1  # disk info block
    image[56:58] = bytes((2, len(files)))  # file amount block
    position = 58
    for number, (file_id, data) in enumerate(files):
        header = bytearray(16)
        header[0] = 3
        header[1] = number
        header[2] = file_id
        header[3:11] = f"FILE{number:04}".encode("ascii")
        header[11:13] = (0x6000).to_bytes(2, "little")
        header[13:15] = len(data).to_bytes(2, "little")
        image[position : position + 16] = header
        image[position + 16] = 4
        image[position + 17 : position + 17 + len(data)] = data
        position += 17 + len(data)
    image[position : position + len(tail)] = tail
    return bytes(image)


class FdsSideTests(unittest.TestCase):
    def test_declared_files_are_read(self) -> None:
        records = parse_fds_side(side([(7, b"abc"), (9, b"defg")]))
        self.assertEqual([(7, 3), (9, 4)], [(record.file_id, record.size) for record in records])
        self.assertEqual(58 + 17, records[0].data_offset)

    def test_data_after_the_declared_files_is_kept_with_a_warning(self) -> None:
        # A hidden file past the declared count, as games keep them.
        hidden = bytes((3, 1, 0x20)) + bytes(13) + bytes((4,)) + b"hidden"
        image = side([(7, b"abc")], hidden)
        inspected = inspect_fds_side(image)
        self.assertEqual(1, len(inspected.records))
        self.assertEqual(58 + 17 + 3, inspected.trailing_offset)
        self.assertEqual(hidden, inspected.trailing_data)
        self.assertEqual(1, len(inspected.warnings))
        self.assertEqual(inspected.records, parse_fds_side(image))

    def test_a_zero_padded_side_has_no_trailing_data(self) -> None:
        inspected = inspect_fds_side(side([(7, b"abc")]))
        self.assertEqual((b"", ()), (inspected.trailing_data, inspected.warnings))


class FdsRefusalTests(unittest.TestCase):
    def assertRefused(self, image: bytes, message: str) -> None:
        with self.assertRaisesRegex(FdsError, message):
            parse_fds_side(image)

    def test_a_side_of_the_wrong_size_or_block_is_refused(self) -> None:
        good = side([(7, b"abc")])
        self.assertRefused(good[:-1], "65500-byte")
        self.assertRefused(good + b"\0", "65500-byte")
        self.assertRefused(bytes((2,)) + good[1:], "65500-byte")
        broken = bytearray(good)
        broken[56] = 9
        self.assertRefused(bytes(broken), "file-count block")

    def test_a_wrong_file_block_magic_is_refused(self) -> None:
        header = bytearray(side([(7, b"abc")]))
        header[58] = 0x33
        self.assertRefused(bytes(header), "file-header block 0")
        data = bytearray(side([(7, b"abc")]))
        data[58 + 16] = 0x44
        self.assertRefused(bytes(data), "file-data block 0")

    def test_a_file_size_past_the_side_is_refused(self) -> None:
        image = bytearray(side([(7, b"abc")]))
        image[58 + 13 : 58 + 15] = (0xFFFF).to_bytes(2, "little")
        self.assertRefused(bytes(image), "truncated FDS file-data block 0")

    def test_more_declared_files_than_the_side_holds_is_refused(self) -> None:
        image = bytearray(side([(7, b"abc")]))
        image[57] = 2  # the second header would be zero padding
        self.assertRefused(bytes(image), "file-header block 1")


if __name__ == "__main__":
    unittest.main()
