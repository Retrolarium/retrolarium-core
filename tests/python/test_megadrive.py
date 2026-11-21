from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))

from retrolarium_core.megadrive import cartridge_checksum, parse_megadrive, stamp_cartridge_checksum


def cartridge(payload: bytes, padding: bytes = b"", start: int = 0) -> bytes:
    data = bytearray(0x200) + payload + padding
    data[0x100:0x104] = b"SEGA"
    data[4:8] = (start + 0x200).to_bytes(4, "big")
    data[0x1A0:0x1A4] = start.to_bytes(4, "big")
    data[0x1A4:0x1A8] = (start + 0x200 + len(payload) - 1).to_bytes(4, "big")
    data[0x1A8:0x1AC] = (0xFF0000).to_bytes(4, "big")
    data[0x1AC:0x1B0] = (0xFFFFFF).to_bytes(4, "big")
    return bytes(data)


class MegaDriveChecksumTests(unittest.TestCase):
    def test_stamping_and_parsing_ignore_padding_after_the_declared_rom(self):
        image = cartridge(bytes.fromhex("00010002"), bytes.fromhex("00030004"))
        parsed = parse_megadrive(stamp_cartridge_checksum(image))
        self.assertEqual(3, parsed.header.checksum)
        self.assertEqual(3, parsed.computed_checksum)
        self.assertEqual("valid", parsed.checksum_status)

    def test_a_partial_last_word_does_not_consume_the_first_padding_byte(self):
        image = cartridge(bytes.fromhex("000102"), bytes.fromhex("ff0304"))
        parsed = parse_megadrive(stamp_cartridge_checksum(image))
        self.assertEqual(0x0201, parsed.header.checksum)
        self.assertEqual(0x0201, parsed.computed_checksum)
        self.assertEqual("valid", parsed.checksum_status)

    def test_the_declared_cpu_range_is_projected_into_file_offsets(self):
        image = cartridge(bytes.fromhex("00010002"), bytes.fromhex("00030004"), start=0x1000)
        parsed = parse_megadrive(stamp_cartridge_checksum(image))
        self.assertEqual(3, parsed.header.checksum)
        self.assertEqual(3, parsed.computed_checksum)
        self.assertEqual("valid", parsed.checksum_status)

    def test_a_file_shorter_than_the_declared_range_checks_its_available_bytes(self):
        image = bytearray(cartridge(bytes.fromhex("00010002")))
        image[0x1A4:0x1A8] = (0xFFFF).to_bytes(4, "big")
        parsed = parse_megadrive(stamp_cartridge_checksum(bytes(image)))
        self.assertEqual(3, parsed.computed_checksum)
        self.assertEqual("valid", parsed.checksum_status)

    def test_an_unpadded_cartridge_retains_the_full_payload_checksum(self):
        image = cartridge(bytes.fromhex("12345678"))
        stamped = stamp_cartridge_checksum(image)
        parsed = parse_megadrive(stamped)
        self.assertEqual(cartridge_checksum(image), parsed.computed_checksum)
        self.assertEqual("valid", parsed.checksum_status)
        self.assertEqual(stamped, stamp_cartridge_checksum(stamped))

    def test_the_explicit_checksum_end_is_exclusive(self):
        image = bytes(0x200) + bytes.fromhex("0102feff")
        self.assertEqual(0x0100, cartridge_checksum(image, 0x201))
        self.assertEqual(0x0102, cartridge_checksum(image, 0x202))
