from __future__ import annotations

import json
import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))

from retrolarium_core.snes import (
    HIROM_HEADER_OFFSET,
    LOROM_HEADER_OFFSET,
    SnesError,
    cartridge_checksum,
    image_manifest,
    parse_snes,
    rom_offset_aliases,
    rom_offset_to_snes,
    snes_to_rom_offset,
    snes_to_sram_offset,
    snes_to_wram_offset,
)


def cartridge(
    mapping: str,
    *,
    size: int = 0x20000,
    copier_header: bool = False,
    map_mode_byte: int | None = None,
    chipset: int = 0,
    ram_size_code: int = 0,
    reset: int = 0x9000,
) -> bytes:
    data = bytearray([0xFF] * size)
    header_offset = LOROM_HEADER_OFFSET if mapping == "lorom" else HIROM_HEADER_OFFSET
    header = memoryview(data)[header_offset : header_offset + 0x40]
    header[:] = bytes(0x40)
    header[0:21] = b"RETROLARIUM SNES TEST".ljust(21)
    header[0x15] = map_mode_byte if map_mode_byte is not None else (0x30 if mapping == "lorom" else 0x21)
    header[0x16] = chipset
    header[0x17] = size.bit_length() - 1 - 10
    header[0x18] = ram_size_code
    header[0x19] = 1
    header[0x1A] = 0x33
    header[0x1B] = 0
    for offset, value in (
        (0x24, 0x9020),
        (0x2A, 0x9010),
        (0x2E, 0x9030),
        (0x34, 0x9020),
        (0x3A, 0x9010),
        (0x3C, reset),
        (0x3E, 0x9030),
    ):
        header[offset : offset + 2] = value.to_bytes(2, "little")
    header.release()
    checksum = (cartridge_checksum(data) + 0x1FE) & 0xFFFF
    data[header_offset + 0x1C : header_offset + 0x1E] = (checksum ^ 0xFFFF).to_bytes(2, "little")
    data[header_offset + 0x1E : header_offset + 0x20] = checksum.to_bytes(2, "little")
    container = bytes(data)
    if copier_header:
        container = bytes([0x5A] * 0x200) + container
    return container


class SnesTests(unittest.TestCase):
    def test_image_schema_is_versioned_and_matches_manifest_keys(self) -> None:
        schema_path = (
            Path(__file__).resolve().parents[2]
            / "python"
            / "retrolarium_core"
            / "schemas"
            / "snes-image-v1.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        manifest = image_manifest(parse_snes(cartridge("lorom")))
        self.assertEqual("retrolarium.snes.image", schema["properties"]["schema"]["const"])
        self.assertEqual(1, schema["properties"]["schema_version"]["const"])
        self.assertEqual(set(schema["required"]), set(manifest))

    def test_parses_fast_lorom_header_vectors_checksum_and_mirrors(self) -> None:
        image = parse_snes(cartridge("lorom"))

        self.assertEqual("lorom", image.header.map_mode)
        self.assertEqual("fast", image.header.speed)
        self.assertEqual(LOROM_HEADER_OFFSET, image.header_offset)
        self.assertEqual("valid", image.checksum_status)
        self.assertEqual(0x9000, image.reset_vector.cpu_address)
        self.assertEqual(0x1000, image.reset_vector.rom_offset)
        self.assertEqual(0x1000, snes_to_rom_offset(image, 0x009000))
        self.assertEqual(0x1000, snes_to_rom_offset(image, 0x809000))
        self.assertEqual(0x1000, snes_to_rom_offset(image, 0x049000))
        self.assertEqual(0x009000, rom_offset_to_snes(image, 0x1000))
        self.assertEqual((0x009000, 0x809000), rom_offset_aliases(image, 0x1000))
        self.assertEqual(16, len(image.vector_table))
        self.assertEqual("nmi", image.vector_table[5].name)
        self.assertEqual("reset", image.vector_table[14].name)

        manifest = image_manifest(image)
        self.assertEqual("retrolarium.snes.image", manifest["schema"])
        self.assertEqual("w65c816", manifest["cpu"])
        self.assertEqual("little", manifest["byte_order"])
        self.assertTrue(any(item["kind"] == "wram" for item in manifest["bus_windows"]))
        self.assertEqual([], manifest["warnings"])

    def test_parses_hirom_and_full_bank_aliases(self) -> None:
        image = parse_snes(cartridge("hirom"))

        self.assertEqual("hirom", image.header.map_mode)
        self.assertEqual("slow", image.header.speed)
        self.assertEqual(HIROM_HEADER_OFFSET, image.header_offset)
        self.assertEqual(0x9000, image.reset_vector.rom_offset)
        self.assertEqual(0x9000, snes_to_rom_offset(image, 0x009000))
        self.assertEqual(0x1234, snes_to_rom_offset(image, 0x401234))
        self.assertEqual(0x1234, snes_to_rom_offset(image, 0xC01234))
        self.assertEqual(0xC01234, rom_offset_to_snes(image, 0x1234))
        self.assertEqual((0x401234, 0xC01234), rom_offset_aliases(image, 0x1234))

    def test_preserves_optional_copier_header_as_a_container_region(self) -> None:
        payload = cartridge("lorom", copier_header=True)
        image = parse_snes(payload)

        self.assertEqual(0x200, image.copier_header_size)
        self.assertEqual(payload, image.copier_header + image.data)
        self.assertEqual("copier_header", image.regions[0].name)
        self.assertEqual(0x200, image.regions[0].size)
        self.assertEqual(len(payload), sum(item.size for item in image.regions))

    def test_reports_checksum_and_declared_size_without_discarding_image(self) -> None:
        data = bytearray(cartridge("lorom"))
        data[-1] ^= 0x01
        image = parse_snes(bytes(data))
        self.assertEqual("mismatch", image.checksum_status)
        self.assertIn("mismatch", image.warnings[-1])

        data = bytearray(cartridge("lorom"))
        data[LOROM_HEADER_OFFSET + 0x17] = 8
        image = parse_snes(bytes(data))
        self.assertIn("declared ROM size", image.warnings[0])

    def test_rejects_exrom_enhancement_chips_and_unbacked_reset(self) -> None:
        with self.assertRaisesRegex(SnesError, "ExLoROM"):
            parse_snes(cartridge("lorom", map_mode_byte=0x32))
        with self.assertRaisesRegex(SnesError, "ExHiROM"):
            parse_snes(cartridge("hirom", map_mode_byte=0x25))
        with self.assertRaisesRegex(SnesError, "enhancement chipset"):
            parse_snes(cartridge("lorom", chipset=0x03))
        with self.assertRaisesRegex(SnesError, "RESET vector"):
            parse_snes(cartridge("lorom", reset=0x1000))

    def test_rejects_invalid_container_sizes_and_non_rom_windows(self) -> None:
        with self.assertRaisesRegex(SnesError, "32 KiB ROM multiple"):
            parse_snes(bytes(0x8001))
        image = parse_snes(cartridge("lorom"))
        with self.assertRaisesRegex(SnesError, "work RAM"):
            snes_to_rom_offset(image, 0x7E9000)
        with self.assertRaisesRegex(SnesError, "LoROM window"):
            snes_to_rom_offset(image, 0x001000)
        with self.assertRaisesRegex(SnesError, "outside"):
            rom_offset_to_snes(image, len(image.data))

    def test_maps_wram_mirrors_and_standard_sram_windows(self) -> None:
        self.assertEqual(0x1234, snes_to_wram_offset(0x001234))
        self.assertEqual(0x11234, snes_to_wram_offset(0x7F1234))
        with self.assertRaisesRegex(SnesError, "WRAM window"):
            snes_to_wram_offset(0x002000)

        lorom = parse_snes(cartridge("lorom", ram_size_code=3))
        self.assertEqual(0, snes_to_sram_offset(lorom, 0x700000))
        self.assertEqual(0, snes_to_sram_offset(lorom, 0xF00000))
        self.assertEqual(0x1FFF, snes_to_sram_offset(lorom, 0x707FFF))
        self.assertTrue(any(item.kind == "sram" for item in lorom.bus_windows))

        hirom = parse_snes(cartridge("hirom", ram_size_code=3))
        self.assertEqual(0, snes_to_sram_offset(hirom, 0x206000))
        self.assertEqual(0, snes_to_sram_offset(hirom, 0xA06000))
        self.assertEqual(0x1FFF, snes_to_sram_offset(hirom, 0x207FFF))
        with self.assertRaisesRegex(SnesError, "HiROM SRAM"):
            snes_to_sram_offset(hirom, 0x208000)

    def test_non_power_of_two_checksum_and_rom_mirroring(self) -> None:
        data = bytes([1]) * 0x10000 + bytes([2]) * 0x8000
        self.assertEqual((0x10000 + 2 * 0x10000) & 0xFFFF, cartridge_checksum(data))

        image = parse_snes(cartridge("lorom", size=0x18000))
        self.assertEqual(
            snes_to_rom_offset(image, 0x029000),
            snes_to_rom_offset(image, 0x039000),
        )


if __name__ == "__main__":
    unittest.main()
