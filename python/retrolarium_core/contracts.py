"""Validation for versioned Retrolarium integration artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class ContractError(ValueError):
    """A generated manifest is unsafe or contradicts its artifacts."""


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{name} must be an object")
    return value


def artifact_path(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ContractError("artifact path must be a non-empty string")
    relative = Path(value)
    if relative.is_absolute():
        raise ContractError(f"artifact path must be relative: {value}")
    root = root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ContractError(f"artifact path escapes project root: {value}") from exc
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_hashed_file(root: Path, record: dict[str, Any], name: str) -> Path:
    path = artifact_path(root, record.get("path"))
    if not path.is_file():
        raise ContractError(f"{name} artifact does not exist: {path}")
    expected = record.get("sha256")
    actual = _sha256(path)
    if expected != actual:
        raise ContractError(f"{name} artifact SHA-256 is {actual}, expected {expected}")
    return path


def validate_nes_disassembly_manifest(
    manifest: dict[str, Any], root: Path, *, verify_rebuilt: bool = True
) -> None:
    if manifest.get("schema") != "retrolarium.nes.disassembly":
        raise ContractError("unsupported disassembly manifest schema")
    if manifest.get("schema_version") != 1:
        raise ContractError("unsupported disassembly manifest version")
    if manifest.get("task") != "nes.disassemble":
        raise ContractError("manifest is not a NES disassembly project")

    input_record = _mapping(manifest.get("input"), "input")
    input_sha256 = input_record.get("sha256")
    input_size = input_record.get("size")
    if not isinstance(input_sha256, str) or len(input_sha256) != 64:
        raise ContractError("input.sha256 must be a SHA-256 string")
    if not isinstance(input_size, int) or input_size <= 0:
        raise ContractError("input.size must be a positive integer")

    backend = _mapping(manifest.get("backend"), "backend")
    analysis_root = artifact_path(root, backend.get("analysis_root"))
    banks = backend.get("banks")
    if not isinstance(banks, list) or not banks:
        raise ContractError("backend.banks must be a non-empty list")
    for index, value in enumerate(banks):
        bank = _mapping(value, f"backend.banks[{index}]")
        _validate_hashed_file(analysis_root, {
            "path": bank.get("analysis_input"),
            "sha256": bank.get("analysis_input_sha256"),
        }, f"bank {index} analysis input")
        _validate_hashed_file(analysis_root, {
            "path": bank.get("facts"),
            "sha256": bank.get("facts_sha256"),
        }, f"bank {index} facts")

    facts = _mapping(manifest.get("facts"), "facts")
    symbols = _mapping(manifest.get("symbols"), "symbols")
    pointers = _mapping(manifest.get("pointers"), "pointers")
    _validate_hashed_file(root, facts, "facts")
    _validate_hashed_file(root, symbols, "symbols")
    _validate_hashed_file(root, pointers, "pointers")

    source = _mapping(manifest.get("source"), "source")
    units = source.get("units")
    if not isinstance(units, list) or not units:
        raise ContractError("source.units must be a non-empty list")
    for unit in units:
        path = artifact_path(root, unit)
        if not path.is_file():
            raise ContractError(f"source unit does not exist: {path}")

    operations = _mapping(manifest.get("operations"), "operations")
    build = _mapping(operations.get("build"), "operations.build")
    verify = _mapping(operations.get("verify"), "operations.verify")
    launch = _mapping(operations.get("launch"), "operations.launch")
    expected_ids = {
        "build": (build, "retrolarium.project.build"),
        "verify": (verify, "retrolarium.project.verify"),
        "launch": (launch, "retrolarium.project.launch"),
    }
    for name, (record, expected_id) in expected_ids.items():
        if record.get("id") != expected_id:
            raise ContractError(f"unsupported {name} operation")
    project_directory = artifact_path(root, build.get("project_directory"))
    if not project_directory.is_dir():
        raise ContractError("build project directory does not exist")
    operation_artifact = build.get("output")
    if not (
        operation_artifact == verify.get("artifact") == launch.get("artifact")
    ):
        raise ContractError("build, verify and launch artifacts differ")
    artifact_path(root, operation_artifact)
    if verify.get("expected_sha256") != input_sha256:
        raise ContractError("verify operation SHA-256 differs from input")
    if verify.get("expected_size") != input_size:
        raise ContractError("verify operation size differs from input")
    if launch.get("platform") != "nes" or launch.get("default_machine") != "nes":
        raise ContractError("unsupported NES launch operation")
    if launch.get("supported_machines") != ["famicom", "nes", "nespal"]:
        raise ContractError("unsupported NES launch machine set")
    if launch.get("supported_modes") != ["interactive-plan", "smoke"]:
        raise ContractError("unsupported NES launch mode set")

    assets = _mapping(manifest.get("assets"), "assets")
    items = assets.get("items")
    if not isinstance(items, list) or not items:
        raise ContractError("assets.items must be a non-empty list")
    identifiers: set[str] = set()
    for index, value in enumerate(items):
        item = _mapping(value, f"assets.items[{index}]")
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ContractError(f"assets.items[{index}] has no id")
        if identifier in identifiers:
            raise ContractError(f"duplicate asset id: {identifier}")
        identifiers.add(identifier)
        path = artifact_path(root, item.get("path"))
        if not path.is_file():
            raise ContractError(f"asset does not exist: {path}")
        offset = item.get("asset_file_offset")
        size = item.get("size")
        if not isinstance(offset, int) or not isinstance(size, int):
            raise ContractError(f"asset {identifier} has invalid slice coordinates")
        payload = path.read_bytes()[offset:offset + size]
        actual = hashlib.sha256(payload).hexdigest()
        if len(payload) != size or actual != item.get("sha256"):
            raise ContractError(f"asset {identifier} slice does not match manifest")

    verification = _mapping(manifest.get("verification"), "verification")
    if verify_rebuilt and verification.get("status") == "exact":
        rebuilt = artifact_path(root, verify.get("artifact"))
        if not rebuilt.is_file():
            raise ContractError("exact verification names a missing rebuilt ROM")
        rebuilt_sha256 = _sha256(rebuilt)
        if rebuilt_sha256 != verification.get("rebuilt_sha256"):
            raise ContractError("rebuilt ROM no longer matches exact verification")
        if not (
            verification.get("original_sha256")
            == verification.get("rebuilt_sha256")
            == input_sha256
        ):
            raise ContractError("exact verification does not match manifest input")
        if rebuilt.stat().st_size != input_size:
            raise ContractError("rebuilt ROM size does not match manifest input")


def _require_sha256(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ContractError(f"{name} must be a lowercase SHA-256 string")
    return value


def _read_json_artifact(path: Path, name: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {name}: {exc}") from exc
    return _mapping(value, name)


def _validate_megadrive_assets(
    manifest: dict[str, Any], root: Path, input_size: int
) -> None:
    assets = _mapping(manifest.get("assets"), "assets")
    if (
        assets.get("schema") != "retrolarium.assets"
        or assets.get("schema_version") != 1
    ):
        raise ContractError("unsupported Mega Drive asset manifest")
    items = assets.get("items")
    if not isinstance(items, list) or not items:
        raise ContractError("assets.items must be a non-empty list")
    identifiers: set[str] = set()
    occupied: list[tuple[int, int]] = []
    for index, value in enumerate(items):
        item = _mapping(value, f"assets.items[{index}]")
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ContractError(f"assets.items[{index}] has no id")
        if identifier in identifiers:
            raise ContractError(f"duplicate asset id: {identifier}")
        identifiers.add(identifier)
        path = _validate_hashed_file(root, item, f"asset {identifier}")
        offset = item.get("rom_file_offset")
        size = item.get("size")
        if (
            not isinstance(offset, int)
            or not isinstance(size, int)
            or offset < 0
            or size <= 0
            or offset + size > input_size
        ):
            raise ContractError(f"asset {identifier} has invalid ROM coordinates")
        if path.stat().st_size != size:
            raise ContractError(f"asset {identifier} size differs from its file")
        occupied.append((offset, offset + size))
    occupied.sort()
    if any(left[1] > right[0] for left, right in zip(occupied, occupied[1:])):
        raise ContractError("Mega Drive asset ROM ranges overlap")


def validate_megadrive_disassembly_manifest(
    manifest: dict[str, Any], root: Path, *, verify_rebuilt: bool = True
) -> None:
    """Validate the public v1 dual-CPU Mega Drive project contract."""
    if manifest.get("schema") != "retrolarium.megadrive.disassembly":
        raise ContractError("unsupported Mega Drive disassembly manifest schema")
    if manifest.get("schema_version") != 1:
        raise ContractError("unsupported Mega Drive disassembly manifest version")
    if manifest.get("task") != "megadrive.disassemble":
        raise ContractError("manifest is not a Mega Drive disassembly project")
    if manifest.get("mode") != "blind":
        raise ContractError("unsupported Mega Drive project mode")

    input_record = _mapping(manifest.get("input"), "input")
    if (
        input_record.get("schema") != "retrolarium.megadrive.image"
        or input_record.get("schema_version") != 1
    ):
        raise ContractError("unsupported Mega Drive input image contract")
    input_sha256 = _require_sha256(input_record.get("sha256"), "input.sha256")
    input_size = input_record.get("size")
    if not isinstance(input_size, int) or input_size < 0x200:
        raise ContractError("input.size must contain a Mega Drive header")
    if input_record.get("byte_order") != "big" or input_record.get("cpu") != "m68000":
        raise ContractError("unsupported Mega Drive input architecture")

    records: dict[str, tuple[Path, dict[str, Any]]] = {}
    for name in ("analysis", "pointers", "symbols", "cross_cpu_evidence"):
        record = _mapping(manifest.get(name), name)
        path = _validate_hashed_file(root, record, name)
        records[name] = (path, _read_json_artifact(path, name))

    analysis_path, analysis = records["analysis"]
    if (
        analysis.get("schema") != "retrolarium.megadrive.analysis"
        or analysis.get("schema_version") != 1
        or analysis.get("task") != "megadrive.analyze"
    ):
        raise ContractError("unsupported Mega Drive analysis artifact")
    analysis_input = _mapping(analysis.get("input"), "analysis.input")
    if analysis_input.get("sha256") != input_sha256 or analysis_input.get("size") != input_size:
        raise ContractError("analysis input differs from project input")
    programs = analysis.get("programs")
    if not isinstance(programs, list) or not programs:
        raise ContractError("analysis.programs must be a non-empty list")
    if manifest["analysis"].get("program_count") != len(programs):
        raise ContractError("analysis program count differs from artifact")
    analysis_root = analysis_path.parent
    cpu_ids: set[str] = set()
    derived_edges: set[str] = set()
    spaces: set[str] = set()
    for index, value in enumerate(programs):
        program = _mapping(value, f"analysis.programs[{index}]")
        cpu_id = program.get("cpu_id")
        space = program.get("address_space")
        if not isinstance(cpu_id, str) or not cpu_id or cpu_id in cpu_ids:
            raise ContractError(f"analysis.programs[{index}] has invalid cpu_id")
        if space not in {"m68k", "z80"}:
            raise ContractError(f"analysis.programs[{index}] has invalid address space")
        cpu_ids.add(cpu_id)
        spaces.add(space)
        expected_language = "68000:BE:32:default" if space == "m68k" else "z80:LE:16:default"
        expected_order = "big" if space == "m68k" else "little"
        if program.get("language") != expected_language or program.get("byte_order") != expected_order:
            raise ContractError(f"analysis program {cpu_id} has inconsistent architecture")
        for field, hash_field in (
            ("analysis_input", "analysis_input_sha256"),
            ("instructions", "instructions_sha256"),
            ("raw_facts", "raw_facts_sha256"),
            ("report", "report_sha256"),
        ):
            _validate_hashed_file(
                analysis_root,
                {"path": program.get(field), "sha256": program.get(hash_field)},
                f"analysis program {cpu_id} {field}",
            )
        if space == "m68k":
            if program.get("analysis_input_sha256") != input_sha256:
                raise ContractError("m68k analysis input differs from cartridge image")
        else:
            edge = program.get("derived_from")
            if not isinstance(edge, str) or not edge:
                raise ContractError(f"Z80 analysis program {cpu_id} has no derivation")
            derived_edges.add(edge)
    if "m68k" not in spaces:
        raise ContractError("Mega Drive analysis has no m68k program")

    pointers = records["pointers"][1]
    symbols = records["symbols"][1]
    for value, schema, name in (
        (pointers, "retrolarium.megadrive.pointers", "pointers"),
        (symbols, "retrolarium.symbols", "symbols"),
    ):
        if value.get("schema") != schema or value.get("schema_version") != 1:
            raise ContractError(f"unsupported Mega Drive {name} artifact")
        if value.get("input_sha256") != input_sha256:
            raise ContractError(f"{name} input differs from project input")

    evidence = records["cross_cpu_evidence"][1]
    if (
        evidence.get("schema") != "retrolarium.cross-cpu-evidence"
        or evidence.get("schema_version") != 1
        or evidence.get("platform") != "megadrive"
        or evidence.get("input_sha256") != input_sha256
    ):
        raise ContractError("unsupported Mega Drive cross-CPU evidence artifact")
    edges = evidence.get("edges")
    if not isinstance(edges, list):
        raise ContractError("cross-CPU edges must be an array")
    edge_ids: set[str] = set()
    m68k_program = next(
        _mapping(value, "m68k analysis program")
        for value in programs
        if isinstance(value, dict) and value.get("address_space") == "m68k"
    )
    cartridge = artifact_path(
        analysis_root, m68k_program.get("analysis_input")
    ).read_bytes()
    for index, value in enumerate(edges):
        edge = _mapping(value, f"cross_cpu_evidence.edges[{index}]")
        edge_id = edge.get("id")
        source = _mapping(edge.get("source"), f"edge {index} source")
        target = _mapping(edge.get("target"), f"edge {index} target")
        size = edge.get("size")
        start = source.get("start")
        end = source.get("end")
        target_start = target.get("start")
        target_end = target.get("end")
        if (
            not isinstance(edge_id, str)
            or not edge_id
            or edge_id in edge_ids
            or edge.get("kind") != "memory_copy"
            or edge.get("confidence") != "proven-static-copy"
            or source.get("address_space") != "m68k"
            or target.get("address_space") != "z80"
            or not isinstance(size, int)
            or size <= 0
            or not isinstance(start, int)
            or not isinstance(end, int)
            or end - start + 1 != size
            or not isinstance(target_start, int)
            or not isinstance(target_end, int)
            or target_end - target_start + 1 != size
        ):
            raise ContractError(f"invalid cross-CPU edge at index {index}")
        edge_ids.add(edge_id)
        payload = _validate_hashed_file(
            analysis_root,
            {"path": edge.get("payload"), "sha256": edge.get("payload_sha256")},
            f"cross-CPU edge {edge_id} payload",
        ).read_bytes()
        if start < 0 or end >= len(cartridge) or payload != cartridge[start:end + 1]:
            raise ContractError(f"cross-CPU edge {edge_id} payload is not its ROM slice")
    if derived_edges != edge_ids:
        raise ContractError("Z80 programs and cross-CPU evidence do not correspond")

    _validate_megadrive_assets(manifest, root, input_size)
    source = _mapping(manifest.get("source"), "source")
    if source.get("dialect") != "asm68k-exact-first":
        raise ContractError("unsupported Mega Drive source dialect")
    units = source.get("units")
    if not isinstance(units, list) or not units:
        raise ContractError("source.units must be a non-empty list")
    for unit in units:
        path = artifact_path(root, unit)
        if not path.is_file():
            raise ContractError(f"source unit does not exist: {path}")
    coverage = _mapping(source.get("coverage"), "source.coverage")
    categories = (
        "vector_bytes",
        "instruction_bytes",
        "pointer_bytes",
        "asset_bytes",
        "raw_bytes",
    )
    if coverage.get("rom_bytes") != input_size or any(
        not isinstance(coverage.get(name), int) or coverage[name] < 0 for name in categories
    ) or sum(coverage[name] for name in categories) != input_size:
        raise ContractError("source coverage does not partition the complete ROM")

    operations = _mapping(manifest.get("operations"), "operations")
    build = _mapping(operations.get("build"), "operations.build")
    verify = _mapping(operations.get("verify"), "operations.verify")
    launch = _mapping(operations.get("launch"), "operations.launch")
    if build.get("id") != "retrolarium.project.build" or build.get("runner") != "docker":
        raise ContractError("unsupported Mega Drive build operation")
    argv = build.get("argv")
    if not isinstance(argv, list) or not argv or any(not isinstance(value, str) or not value for value in argv):
        raise ContractError("build argv must be a non-empty string array")
    project_directory = artifact_path(root, build.get("project_directory"))
    if not project_directory.is_dir():
        raise ContractError("build project directory does not exist")
    if not (build.get("output") == verify.get("artifact") == launch.get("artifact")):
        raise ContractError("build, verify and launch artifacts differ")
    artifact_path(root, build.get("output"))
    if (
        verify.get("id") != "retrolarium.project.verify"
        or verify.get("expected_sha256") != input_sha256
        or verify.get("expected_size") != input_size
    ):
        raise ContractError("invalid Mega Drive verification operation")
    if (
        launch.get("id") != "retrolarium.project.launch"
        or launch.get("platform") != "megadrive"
        or launch.get("default_machine") != "genesis"
        or launch.get("supported_machines") != ["genesis", "megadriv"]
        or launch.get("supported_modes") != ["interactive-plan", "smoke"]
    ):
        raise ContractError("invalid Mega Drive launch operation")

    verification = _mapping(manifest.get("verification"), "verification")
    if verify_rebuilt and verification.get("status") == "exact":
        rebuilt = artifact_path(root, verify.get("artifact"))
        if not rebuilt.is_file():
            raise ContractError("exact verification names a missing rebuilt ROM")
        if (
            rebuilt.stat().st_size != input_size
            or _sha256(rebuilt) != input_sha256
            or verification.get("original_sha256") != input_sha256
            or verification.get("rebuilt_sha256") != input_sha256
        ):
            raise ContractError("rebuilt Mega Drive ROM no longer matches exact verification")


def validate_disassembly_manifest(
    manifest: dict[str, Any], root: Path, *, verify_rebuilt: bool = True
) -> None:
    schema = manifest.get("schema")
    if schema == "retrolarium.nes.disassembly":
        validate_nes_disassembly_manifest(
            manifest, root, verify_rebuilt=verify_rebuilt
        )
    elif schema == "retrolarium.megadrive.disassembly":
        validate_megadrive_disassembly_manifest(
            manifest, root, verify_rebuilt=verify_rebuilt
        )
    else:
        raise ContractError("unsupported disassembly manifest schema")


def load_disassembly_manifest(
    path: Path, *, verify_rebuilt: bool = True
) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read disassembly manifest: {exc}") from exc
    manifest = _mapping(value, "manifest")
    validate_disassembly_manifest(
        manifest, path.resolve().parent, verify_rebuilt=verify_rebuilt
    )
    return manifest
