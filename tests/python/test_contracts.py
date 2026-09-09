from __future__ import annotations

import hashlib
import sys
from pathlib import Path
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from retrolarium_kit.contracts import (
    ContractError,
    artifact_path,
    validate_disassembly_manifest,
)


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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


if __name__ == "__main__":
    unittest.main()
