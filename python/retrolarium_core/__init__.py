"""Retrolarium Core for Python: what a ROM is and how its pieces are checked.

Container parsers (iNES, Famicom Disk System, Mega Drive, SNES), the contract a
disassembly manifest keeps, the bridge to the C++ ``rlcore`` tool (the Enigma
and Nemesis codecs exist only in C++; their golden corpora under
tests/fixtures were written by Python ports since removed) and the repository
guards. Nothing here knows about a particular game or about analysis; the kit
and the disassembler both build on it.
"""

# The one version of retrolarium-core: pyproject.toml and CMakeLists.txt's
# project(VERSION), from which rlcore reports it, carry the same number
# (tests/python/test_version.py); retrolarium_core.tool checks rlcore against it.
__version__ = "0.5.0"
