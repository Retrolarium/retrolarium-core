from __future__ import annotations

import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))

from retrolarium_core.ines import (
    InesError,
    address_to_region_offset,
    cpu_to_prg_offset,
    mapper_profile,
    mapper_projections,
    nrom_projections,
    parse_ines,
    prg_analysis_targets,
)
from helpers import nrom16_image


class InesTests(unittest.TestCase):
    @staticmethod
    def banked_image(mapper: int, prg_units: int, chr_units: int) -> bytes:
        flags6 = (mapper & 0x0F) << 4
        flags7 = mapper & 0xF0
        header = b"NES\x1a" + bytes((prg_units, chr_units, flags6, flags7)) + bytes(8)
        prg = b"".join(
            bytes((bank,)) * 0x8000 for bank in range((prg_units + 1) // 2)
        )[:prg_units * 0x4000]
        chr_data = b"".join(bytes((bank,)) * 0x2000 for bank in range(chr_units))
        return header + prg + chr_data

    def test_parses_nrom16_regions_and_mirrors(self) -> None:
        image = parse_ines(nrom16_image())
        self.assertEqual(0, image.mapper)
        self.assertEqual(0x4000, len(image.prg))
        self.assertEqual(0x2000, len(image.chr))
        projections = nrom_projections(image)
        self.assertEqual((0xC000, 0x8000), tuple(item.cpu_start for item in projections))
        self.assertEqual(0, cpu_to_prg_offset(image, 0xC000))
        self.assertEqual(0, cpu_to_prg_offset(image, 0x8000))

    def test_an_old_dumpers_tag_leaves_the_low_mapper_nibble(self) -> None:
        data = bytearray(nrom16_image())
        data[7:16] = b"DiskDude!"
        self.assertEqual(0, parse_ines(bytes(data)).mapper)

    def test_rejects_trailing_bytes(self) -> None:
        with self.assertRaises(InesError):
            parse_ines(nrom16_image() + b"unexpected")

    def test_rejects_nes2_until_profile_exists(self) -> None:
        data = bytearray(nrom16_image())
        data[7] = 0x08
        with self.assertRaises(InesError):
            parse_ines(bytes(data))

    def test_cnrom_projects_fixed_prg_and_selectable_chr_banks(self) -> None:
        image = parse_ines(self.banked_image(3, 2, 4))
        projections = mapper_projections(image)

        self.assertEqual("nes.cnrom", mapper_profile(image).profile_id)
        self.assertEqual(1, sum(item.region == "prg" for item in projections))
        chr_banks = [item for item in projections if item.region == "chr"]
        self.assertEqual([0, 1, 2, 3], [item.bank for item in chr_banks])
        self.assertTrue(
            all(item.selector == "mapper.chr_bank" for item in chr_banks)
        )
        self.assertEqual(
            0x6000,
            address_to_region_offset(image, "chr", "ppu", 0, bank=3),
        )
        targets = prg_analysis_targets(image)
        self.assertEqual(1, len(targets))
        self.assertTrue(targets[0].synthesized)
        self.assertEqual(0, targets[0].image.mapper)
        self.assertEqual(image.prg, targets[0].image.prg)
        self.assertEqual(b"", targets[0].image.chr)

    def test_gnrom_requires_bank_context_for_overlapping_prg_window(self) -> None:
        image = parse_ines(self.banked_image(66, 8, 4))
        projections = mapper_projections(image)

        self.assertEqual("nes.gnrom", mapper_profile(image).profile_id)
        prg_banks = [item for item in projections if item.region == "prg"]
        self.assertEqual([0, 1, 2, 3], [item.bank for item in prg_banks])
        self.assertTrue(
            all(item.selector == "mapper.prg_bank" for item in prg_banks)
        )
        with self.assertRaises(InesError):
            cpu_to_prg_offset(image, 0x8000)
        self.assertEqual(0x10000, cpu_to_prg_offset(image, 0x8000, bank=2))
        targets = prg_analysis_targets(image)
        self.assertEqual([0, 1, 2, 3], [target.bank for target in targets])
        self.assertEqual(
            [bytes((bank,)) * 0x8000 for bank in range(4)],
            [target.image.prg for target in targets],
        )

    def test_nrom_analysis_keeps_the_original_container(self) -> None:
        image = parse_ines(nrom16_image())
        target, = prg_analysis_targets(image)

        self.assertFalse(target.synthesized)
        self.assertIs(image, target.image)

    def test_rejects_mapper_without_profile(self) -> None:
        image = parse_ines(self.banked_image(2, 2, 1))
        with self.assertRaises(InesError):
            mapper_projections(image)


if __name__ == "__main__":
    unittest.main()
