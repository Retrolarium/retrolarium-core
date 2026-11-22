from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))

from retrolarium_core.megadrive import (
    MegaDriveError,
    cartridge_checksum,
    image_manifest,
    m68k_to_rom_offset,
    parse_megadrive,
    stamp_cartridge_checksum,
)


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


class MegaDriveHeaderTests(unittest.TestCase):
    def test_ram_end_past_24_bits_is_a_warning_and_the_work_ram(self):
        image = bytearray(cartridge(bytes.fromhex("00010002")))
        image[0x1AC:0x1B0] = (0xFFFFFFFF).to_bytes(4, "big")
        parsed = parse_megadrive(bytes(image))
        self.assertEqual((0xFF0000, 0xFFFFFF), (parsed.header.ram_start, parsed.header.ram_end))
        self.assertTrue(any("RAM range" in warning for warning in parsed.warnings), parsed.warnings)
        work_ram = parsed.address_ranges[1]
        self.assertEqual((0xFF0000, 0xFFFFFF), (work_ram.cpu_start, work_ram.cpu_end))

    def test_a_garbage_rom_start_does_not_shift_addresses(self):
        image = bytearray(cartridge(bytes.fromhex("00010002"), bytes.fromhex("00030004")))
        image[0x1A0:0x1A4] = b"ROM "
        parsed = parse_megadrive(stamp_cartridge_checksum(bytes(image)))
        self.assertEqual(0, parsed.header.rom_start)
        self.assertTrue(any("ROM start" in warning for warning in parsed.warnings), parsed.warnings)
        self.assertEqual(0x200, parsed.reset_address)
        self.assertEqual(0x200, m68k_to_rom_offset(parsed, parsed.reset_address))
        # The checksum range starts at 0 as well: padding is still excluded.
        self.assertEqual(3, parsed.computed_checksum)
        self.assertEqual("valid", parsed.checksum_status)

    def test_a_declared_rom_origin_still_projects_addresses(self):
        parsed = parse_megadrive(cartridge(bytes.fromhex("00010002"), start=0x1000))
        self.assertEqual(0x1000, parsed.header.rom_start)
        self.assertEqual(0x200, m68k_to_rom_offset(parsed, 0x1200))
        self.assertFalse(any("ROM start" in warning for warning in parsed.warnings))


class MegaDriveRefusalTests(unittest.TestCase):
    def assertRefused(self, image: bytes, message: str) -> None:
        with self.assertRaisesRegex(MegaDriveError, message):
            parse_megadrive(image)

    def test_a_short_image_or_a_missing_signature_is_refused(self):
        image = cartridge(bytes.fromhex("00010002"))
        self.assertRefused(image[:0x1FF], "at least 512")
        unsigned = bytearray(image)
        unsigned[0x100:0x104] = b"GENS"
        self.assertRefused(bytes(unsigned), "SEGA cartridge signature")

    def test_a_reset_vector_outside_the_rom_or_odd_is_refused(self):
        image = bytearray(cartridge(bytes.fromhex("00010002")))
        image[4:8] = (0x201).to_bytes(4, "big")
        self.assertRefused(bytes(image), "reset vector is odd")
        image[4:8] = (0x10000).to_bytes(4, "big")
        self.assertRefused(bytes(image), "outside the file-backed ROM range")

    def test_a_rom_past_the_24_bit_bus_is_refused(self):
        image = bytearray(cartridge(bytes.fromhex("00010002"), start=0xFFFF00))
        self.assertRefused(bytes(image), "24-bit address space")

    def test_an_unset_checksum_is_absent_and_the_manifest_reports_it(self):
        parsed = parse_megadrive(cartridge(bytes.fromhex("00010002")))
        self.assertEqual("absent", parsed.checksum_status)
        manifest = image_manifest(parsed)
        self.assertEqual("absent", manifest["header"]["checksum_status"])
        self.assertEqual([0, 0x100, 0x200], [region["file_offset"] for region in manifest["regions"]])
