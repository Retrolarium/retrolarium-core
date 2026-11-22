from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))

from retrolarium_core.contracts import (
    ContractError,
    artifact_path,
    validate_disassembly_manifest,
)


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write(root: Path, relative: str, payload: bytes | dict) -> dict[str, str]:
    """Write an artifact under root; its {path, sha256} record."""
    if isinstance(payload, dict):
        payload = json.dumps(payload).encode("utf-8")
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {"path": relative, "sha256": digest(payload)}


def megadrive_project(root: Path) -> dict:
    """A minimal valid Mega Drive manifest: a 0x400-byte cartridge, one m68k
    and one Z80 program, a one-byte copy edge between them and one asset."""
    rom = bytes(index & 0xFF for index in range(0x400))
    rom_sha = digest(rom)
    program_files = {}
    for cpu in ("m68k", "z80"):
        for field in ("instructions", "raw_facts", "report"):
            record = write(root / "analysis", f"{cpu}/{field}.json", {"cpu": cpu, "field": field})
            program_files[(cpu, field)] = record
    m68k_input = write(root / "analysis", "m68k/input.bin", rom)
    z80_input = write(root / "analysis", "z80/input.bin", rom[0x300:0x301])
    payload = write(root / "analysis", "z80/payload.bin", rom[0x300:0x301])

    def program(cpu: str, space: str, language: str, order: str, analysis_input: dict) -> dict:
        record = {
            "cpu_id": cpu,
            "address_space": space,
            "language": language,
            "byte_order": order,
            "analysis_input": analysis_input["path"],
            "analysis_input_sha256": analysis_input["sha256"],
        }
        for field in ("instructions", "raw_facts", "report"):
            record[field] = program_files[(cpu, field)]["path"]
            record[f"{field}_sha256"] = program_files[(cpu, field)]["sha256"]
        return record

    z80 = program("z80", "z80", "z80:LE:16:default", "little", z80_input)
    z80["derived_from"] = "edge0"
    analysis = write(
        root,
        "analysis/analysis.json",
        {
            "schema": "retrolarium.megadrive.analysis",
            "schema_version": 1,
            "task": "megadrive.analyze",
            "input": {"sha256": rom_sha, "size": len(rom)},
            "programs": [program("m68k", "m68k", "68000:BE:32:default", "big", m68k_input), z80],
        },
    )
    pointers = write(
        root,
        "analysis/pointers.json",
        {"schema": "retrolarium.megadrive.pointers", "schema_version": 1, "input_sha256": rom_sha},
    )
    symbols = write(
        root, "generated/symbols.json", {"schema": "retrolarium.symbols", "schema_version": 1, "input_sha256": rom_sha}
    )
    edge = {
        "id": "edge0",
        "kind": "memory_copy",
        "confidence": "proven-static-copy",
        "source": {"address_space": "m68k", "start": 0x300, "end": 0x300},
        "target": {"address_space": "z80", "cpu_id": "z80", "start": 0, "end": 0},
        "size": 1,
        "payload": payload["path"],
        "payload_sha256": payload["sha256"],
    }
    evidence = write(
        root,
        "analysis/cross_cpu_evidence.json",
        {
            "schema": "retrolarium.cross-cpu-evidence",
            "schema_version": 1,
            "platform": "megadrive",
            "input_sha256": rom_sha,
            "edges": [edge],
        },
    )
    asset = write(root, "generated/assets/byte.bin", rom[0x10:0x11])
    write(root, "generated/src/main.asm", b"; main\n")
    return {
        "schema": "retrolarium.megadrive.disassembly",
        "schema_version": 1,
        "task": "megadrive.disassemble",
        "mode": "blind",
        "input": {
            "schema": "retrolarium.megadrive.image",
            "schema_version": 1,
            "sha256": rom_sha,
            "size": len(rom),
            "byte_order": "big",
            "cpu": "m68000",
        },
        "analysis": {**analysis, "program_count": 2},
        "pointers": pointers,
        "symbols": symbols,
        "cross_cpu_evidence": evidence,
        "assets": {
            "schema": "retrolarium.assets",
            "schema_version": 1,
            "items": [{"id": "byte", **asset, "rom_file_offset": 0x10, "size": 1}],
        },
        "source": {
            "dialect": "asl-exact-first",
            "units": ["generated/src/main.asm"],
            "coverage": {
                "rom_bytes": len(rom),
                "vector_bytes": 0x100,
                "instruction_bytes": 0x200,
                "pointer_bytes": 0x40,
                "asset_bytes": 1,
                "raw_bytes": 0xBF,
                "symbolic_instruction_bytes": 0x100,
            },
        },
        "operations": {
            "build": {
                "id": "retrolarium.project.build",
                "runner": "docker",
                "argv": ["make"],
                "project_directory": "generated",
                "output": "generated/build/rebuilt.bin",
            },
            "verify": {
                "id": "retrolarium.project.verify",
                "artifact": "generated/build/rebuilt.bin",
                "expected_sha256": rom_sha,
                "expected_size": len(rom),
            },
            "launch": {
                "id": "retrolarium.project.launch",
                "artifact": "generated/build/rebuilt.bin",
                "platform": "megadrive",
                "default_machine": "genesis",
                "supported_machines": ["genesis", "megadriv"],
                "supported_modes": ["interactive-plan", "smoke"],
            },
        },
        "verification": {"status": "not-run"},
    }


class ContractTests(unittest.TestCase):
    def test_artifact_path_rejects_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ContractError):
                artifact_path(Path(directory), "../outside.json")

    def test_manifest_validates_declared_files_hashes_and_asset_slices(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records = {
                "analysis/instructions.json": b"facts",
                "analysis/pointers.json": b"pointers",
                "analysis/banks/bank00/analysis-input.nes": b"rom",
                "analysis/banks/bank00/instructions.tsv": b"tsv",
                "generated/symbols.json": b"symbols",
            }
            for relative, payload in records.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            source = root / "generated/src/prg.asm"
            source.parent.mkdir(parents=True)
            source.write_text('.segment "PRG"\n', encoding="utf-8")
            asset = root / "generated/assets/chr.bin"
            asset.parent.mkdir(parents=True)
            asset.write_bytes(b"prefix" + b"bank-data" + b"suffix")

            manifest = {
                "schema": "retrolarium.nes.disassembly",
                "schema_version": 1,
                "task": "nes.disassemble",
                "input": {"sha256": "0" * 64, "size": 1},
                "backend": {
                    "analysis_root": "analysis",
                    "banks": [
                        {
                            "analysis_input": "banks/bank00/analysis-input.nes",
                            "analysis_input_sha256": digest(b"rom"),
                            "facts": "banks/bank00/instructions.tsv",
                            "facts_sha256": digest(b"tsv"),
                        }
                    ],
                },
                "facts": {
                    "path": "analysis/instructions.json",
                    "sha256": digest(records["analysis/instructions.json"]),
                },
                "symbols": {
                    "path": "generated/symbols.json",
                    "sha256": digest(records["generated/symbols.json"]),
                },
                "pointers": {
                    "path": "analysis/pointers.json",
                    "sha256": digest(records["analysis/pointers.json"]),
                },
                "source": {"units": ["generated/src/prg.asm"]},
                "operations": {
                    "build": {
                        "id": "retrolarium.project.build",
                        "project_directory": "generated",
                        "output": "generated/build/rebuilt.nes",
                        "default_container": None,
                    },
                    "verify": {
                        "id": "retrolarium.project.verify",
                        "artifact": "generated/build/rebuilt.nes",
                        "expected_sha256": "0" * 64,
                        "expected_size": 1,
                    },
                    "launch": {
                        "id": "retrolarium.project.launch",
                        "artifact": "generated/build/rebuilt.nes",
                        "platform": "nes",
                        "default_machine": "nes",
                        "supported_machines": ["famicom", "nes", "nespal"],
                        "supported_modes": ["interactive-plan", "smoke"],
                    },
                },
                "assets": {
                    "items": [
                        {
                            "id": "nes.chr.bank00",
                            "path": "generated/assets/chr.bin",
                            "asset_file_offset": 6,
                            "size": 9,
                            "sha256": digest(b"bank-data"),
                        }
                    ]
                },
                "verification": {"status": "not-run"},
            }

            validate_disassembly_manifest(manifest, root)
            asset.write_bytes(b"prefix" + b"changed!!" + b"suffix")
            with self.assertRaisesRegex(ContractError, "slice does not match"):
                validate_disassembly_manifest(manifest, root)


def snes_project(root: Path) -> dict:
    """A minimal valid SNES manifest: a 0x8000-byte LoROM without a copier
    header, the W65C816 program alone and no SPC700 copies."""
    rom = bytes((index * 7) & 0xFF for index in range(0x8000))
    rom_sha = digest(rom)
    analysis_input = write(root / "analysis", "w65c816/input.sfc", rom)
    state = write(
        root / "analysis",
        "w65c816/state.json",
        {"schema": "retrolarium.snes.state-analysis", "input_sha256": rom_sha, "instructions": [{}, {}]},
    )
    analysis = write(
        root,
        "analysis/analysis.json",
        {
            "schema": "retrolarium.snes.analysis",
            "schema_version": 1,
            "task": "snes.analyze",
            "input": {
                "sha256": rom_sha,
                "rom_sha256": rom_sha,
                "size": len(rom),
                "rom_size": len(rom),
                "mapping": "lorom",
            },
            "programs": [
                {
                    "cpu_id": "w65c816",
                    "address_space": "snes-rom",
                    "language": "65816:LE:24:snes",
                    "byte_order": "little",
                    "status": "independent-state-analysis",
                    "analysis_input": analysis_input["path"],
                    "analysis_input_sha256": analysis_input["sha256"],
                    "instructions": state["path"],
                    "instructions_sha256": state["sha256"],
                    "instruction_count": 2,
                }
            ],
        },
    )
    pointers = write(
        root,
        "analysis/pointers.json",
        {"schema": "retrolarium.snes.pointers", "schema_version": 1, "input_sha256": rom_sha},
    )
    symbols = write(
        root, "generated/symbols.json", {"schema": "retrolarium.symbols", "schema_version": 1, "input_sha256": rom_sha}
    )
    evidence = write(
        root,
        "analysis/cross_cpu_evidence.json",
        {
            "schema": "retrolarium.cross-cpu-evidence",
            "schema_version": 1,
            "platform": "snes",
            "input_sha256": rom_sha,
            "edges": [],
        },
    )
    write(root, "generated/src/main.s", b"; main\n")
    emission = write(root, "generated/emission.json", {"units": 1})
    return {
        "schema": "retrolarium.snes.disassembly",
        "schema_version": 1,
        "task": "snes.disassemble",
        "mode": "blind",
        "input": {
            "schema": "retrolarium.snes.image",
            "schema_version": 1,
            "container_sha256": rom_sha,
            "rom_sha256": rom_sha,
            "container_size": len(rom),
            "rom_size": len(rom),
            "copier_header_size": 0,
            "cpu": "w65c816",
            "byte_order": "little",
            "mapping": "lorom",
        },
        "analysis": {**analysis, "program_count": 1},
        "pointers": pointers,
        "symbols": symbols,
        "cross_cpu_evidence": {**evidence, "edge_count": 0},
        "assets": {"schema": "retrolarium.assets", "schema_version": 1, "items": []},
        "source": {
            "dialect": "ca65",
            "whole_rom_fallback": False,
            "units": ["generated/src/main.s"],
            "emission": emission,
            "coverage": {
                "rom_bytes": len(rom),
                "copier_header_bytes": 0,
                "instruction_bytes": 0x4000,
                "instruction_fallback_bytes": 0x100,
                "pointer_bytes": 0x100,
                "header_bytes": 0x50,
                "raw_bytes": 0x8000 - 0x4000 - 0x100 - 0x100 - 0x50,
            },
        },
        "operations": {
            "build": {
                "id": "retrolarium.project.build",
                "runner": "docker",
                "argv": ["make", "all"],
                "project_directory": "generated",
                "output": "generated/build/rebuilt.sfc",
            },
            "verify": {
                "id": "retrolarium.project.verify",
                "artifact": "generated/build/rebuilt.sfc",
                "expected_sha256": rom_sha,
                "expected_size": len(rom),
            },
            "launch": {
                "id": "retrolarium.project.launch",
                "artifact": "generated/build/rebuilt.sfc",
                "platform": "snes",
                "default_machine": "snes",
                "supported_machines": ["snes", "snespal"],
                "supported_modes": ["interactive-plan", "smoke"],
            },
        },
        "verification": {"status": "not-run"},
    }


class MegaDriveContractTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.manifest = megadrive_project(self.root)

    def refused(self, manifest: dict, message: str) -> None:
        with self.assertRaisesRegex(ContractError, message):
            validate_disassembly_manifest(manifest, self.root)

    def test_a_complete_project_validates(self) -> None:
        validate_disassembly_manifest(self.manifest, self.root)

    def test_a_bool_is_not_an_asset_size(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["assets"]["items"][0]["size"] = True
        self.refused(manifest, "invalid ROM coordinates")

    def test_a_bool_is_not_an_edge_size(self) -> None:
        evidence = json.loads((self.root / "analysis/cross_cpu_evidence.json").read_text(encoding="utf-8"))
        evidence["edges"][0]["size"] = True
        manifest = copy.deepcopy(self.manifest)
        manifest["cross_cpu_evidence"] = write(self.root, "analysis/cross_cpu_evidence.json", evidence)
        self.refused(manifest, "invalid cross-CPU edge")

    def test_coverage_that_does_not_partition_the_rom_is_refused(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["source"]["coverage"]["raw_bytes"] -= 1
        self.refused(manifest, "does not partition")

    def test_a_copy_edge_whose_payload_is_not_its_rom_slice_is_refused(self) -> None:
        payload = write(self.root / "analysis", "z80/payload.bin", b"\xee")
        evidence = json.loads((self.root / "analysis/cross_cpu_evidence.json").read_text(encoding="utf-8"))
        evidence["edges"][0]["payload_sha256"] = payload["sha256"]
        manifest = copy.deepcopy(self.manifest)
        manifest["cross_cpu_evidence"] = write(self.root, "analysis/cross_cpu_evidence.json", evidence)
        self.refused(manifest, "payload is not its ROM slice")

    def test_a_changed_artifact_or_an_unknown_machine_is_refused(self) -> None:
        (self.root / "analysis/pointers.json").write_text("{}", encoding="utf-8")
        self.refused(self.manifest, "pointers artifact SHA-256")
        manifest = megadrive_project(self.root)
        manifest["operations"]["launch"]["default_machine"] = "megacd"
        self.refused(manifest, "invalid Mega Drive launch operation")


class SnesContractTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.manifest = snes_project(self.root)

    def refused(self, manifest: dict, message: str) -> None:
        with self.assertRaisesRegex(ContractError, message):
            validate_disassembly_manifest(manifest, self.root)

    def test_a_complete_project_validates(self) -> None:
        validate_disassembly_manifest(self.manifest, self.root)

    def test_inconsistent_sizes_or_a_bool_size_are_refused(self) -> None:
        for field, value in (("copier_header_size", 512), ("container_size", True), ("mapping", "exhirom")):
            manifest = copy.deepcopy(self.manifest)
            manifest["input"][field] = value
            self.refused(manifest, "inconsistent SNES input")

    def test_an_analysis_input_that_is_not_the_rom_is_refused(self) -> None:
        changed = write(self.root / "analysis", "w65c816/input.sfc", bytes(0x8000))
        analysis = json.loads((self.root / "analysis/analysis.json").read_text(encoding="utf-8"))
        analysis["programs"][0]["analysis_input_sha256"] = changed["sha256"]
        manifest = copy.deepcopy(self.manifest)
        manifest["analysis"] = {**write(self.root, "analysis/analysis.json", analysis), "program_count": 1}
        self.refused(manifest, "differs from cartridge ROM")

    def test_coverage_or_operations_that_do_not_match_are_refused(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["source"]["coverage"]["header_bytes"] += 1
        self.refused(manifest, "does not partition")
        manifest = copy.deepcopy(self.manifest)
        manifest["operations"]["build"]["argv"] = ["make"]
        self.refused(manifest, "operation contract")
        manifest = copy.deepcopy(self.manifest)
        manifest["cross_cpu_evidence"]["edge_count"] = 1
        self.refused(manifest, "edge count")


if __name__ == "__main__":
    unittest.main()
