"""Retrolarium Core for Python: what a ROM is and how its pieces are checked.

Container parsers (iNES, Famicom Disk System, Mega Drive, SNES), the contract a
disassembly manifest keeps, the bridge to the C++ ``rlcore`` tool and the
reference Enigma/Nemesis codecs its C++ port is tested against. Nothing here
knows about a particular game or about analysis; the kit and the disassembler
both build on it.
"""
