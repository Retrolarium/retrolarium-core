"""Small images the core tests build on."""
from __future__ import annotations


def nrom16_image() -> bytes:
    header = b"NES\x1a" + bytes((1, 1, 0, 0)) + bytes(8)
    prg = bytearray(0x4000)
    prg[0:6] = bytes.fromhex("2C 02 20 10 FB 60")
    prg[-6:] = bytes.fromhex("00 C0 00 C0 00 00")
    chr_data = bytes((index & 0xFF for index in range(0x2000)))
    return header + prg + chr_data
