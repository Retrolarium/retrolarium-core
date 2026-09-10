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


def _validate_build_runner(
    root: Path,
    build: dict[str, Any],
    *,
    suite: str,
    recipe: str,
) -> None:
    runner = build.get("runner")
    if runner not in (None, "docker", "retrolarium-kit"):
        raise ContractError(f"unsupported build runner: {runner!r}")
    argv = build.get("argv")
    if argv is not None and (
        not isinstance(argv, list)
        or not argv
        or any(not isinstance(value, str) or not value for value in argv)
    ):
        raise ContractError("build argv must be a non-empty string array")
    if runner != "retrolarium-kit":
        return
    if build.get("toolchain_suite") != suite or build.get("recipe") != recipe:
        raise ContractError("bundled build suite or recipe does not match the platform")
    project_directory = artifact_path(root, build.get("project_directory"))
    fields = (
        ("source", "linker_config", "object", "map")
        if recipe == "ca65-ld65-v1"
        else ("source", "object")
    )
    for field in fields:
        artifact_path(project_directory, build.get(field))
    output = artifact_path(root, build.get("output"))
    try:
        output.relative_to(project_directory)
    except ValueError as exc:
        raise ContractError("build output must be inside project_directory") from exc


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
    _validate_build_runner(
        root, build, suite="nes", recipe="ca65-ld65-v1"
    )
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
    if source.get("dialect") not in {"asm68k-exact-first", "asl-exact-first"}:
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
    if (
        build.get("id") != "retrolarium.project.build"
        or build.get("runner") not in {"docker", "retrolarium-kit"}
    ):
        raise ContractError("unsupported Mega Drive build operation")
    argv = build.get("argv")
    if not isinstance(argv, list) or not argv or any(not isinstance(value, str) or not value for value in argv):
        raise ContractError("build argv must be a non-empty string array")
    project_directory = artifact_path(root, build.get("project_directory"))
    if not project_directory.is_dir():
        raise ContractError("build project directory does not exist")
    _validate_build_runner(
        root, build, suite="megadrive", recipe="asl-p2bin-v1"
    )
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


def validate_snes_disassembly_manifest(
    manifest: dict[str, Any], root: Path, *, verify_rebuilt: bool = True
) -> None:
    """Validate the public v1 multi-program plain LoROM/HiROM contract."""
    if manifest.get("schema") != "retrolarium.snes.disassembly":
        raise ContractError("unsupported SNES disassembly manifest schema")
    if manifest.get("schema_version") != 1 or manifest.get("task") != "snes.disassemble":
        raise ContractError("unsupported SNES disassembly manifest version or task")
    if manifest.get("mode") != "blind":
        raise ContractError("unsupported SNES project mode")

    image = _mapping(manifest.get("input"), "input")
    if image.get("schema") != "retrolarium.snes.image" or image.get("schema_version") != 1:
        raise ContractError("unsupported SNES input image contract")
    container_sha = _require_sha256(image.get("container_sha256"), "input.container_sha256")
    rom_sha = _require_sha256(image.get("rom_sha256"), "input.rom_sha256")
    container_size = image.get("container_size")
    rom_size = image.get("rom_size")
    copier_size = image.get("copier_header_size")
    if (
        image.get("cpu") != "w65c816"
        or image.get("byte_order") != "little"
        or image.get("mapping") not in {"lorom", "hirom"}
        or not isinstance(container_size, int)
        or not isinstance(rom_size, int)
        or not isinstance(copier_size, int)
        or container_size != rom_size + copier_size
        or copier_size not in {0, 512}
    ):
        raise ContractError("inconsistent SNES input architecture or sizes")

    records: dict[str, tuple[Path, dict[str, Any]]] = {}
    for name in ("analysis", "pointers", "symbols", "cross_cpu_evidence"):
        record = _mapping(manifest.get(name), name)
        path = _validate_hashed_file(root, record, name)
        records[name] = (path, _read_json_artifact(path, name))
    analysis_path, analysis = records["analysis"]
    if (
        analysis.get("schema") != "retrolarium.snes.analysis"
        or analysis.get("schema_version") != 1
        or analysis.get("task") != "snes.analyze"
    ):
        raise ContractError("unsupported SNES analysis artifact")
    analyzed_input = _mapping(analysis.get("input"), "analysis.input")
    if (
        analyzed_input.get("sha256") != container_sha
        or analyzed_input.get("rom_sha256") != rom_sha
        or analyzed_input.get("size") != container_size
        or analyzed_input.get("rom_size") != rom_size
        or analyzed_input.get("mapping") != image.get("mapping")
    ):
        raise ContractError("SNES analysis input differs from project input")
    programs = analysis.get("programs")
    if (
        not isinstance(programs, list)
        or not programs
        or manifest["analysis"].get("program_count") != len(programs)
    ):
        raise ContractError("SNES analysis program count is invalid")
    analysis_root = analysis_path.parent
    cpu_ids: set[str] = set()
    derived_edges: set[str] = set()
    main_payload: bytes | None = None
    for index, value in enumerate(programs):
        program = _mapping(value, f"analysis.programs[{index}]")
        cpu_id = program.get("cpu_id")
        space = program.get("address_space")
        if not isinstance(cpu_id, str) or not cpu_id or cpu_id in cpu_ids:
            raise ContractError(f"analysis.programs[{index}] has invalid cpu_id")
        cpu_ids.add(cpu_id)
        expected = {
            "snes-rom": ("65816:LE:24:snes", "little"),
            "spc700-ram": ("SPC700:LE:16:default", "little"),
        }.get(space)
        if expected is None or (program.get("language"), program.get("byte_order")) != expected:
            raise ContractError(f"analysis program {cpu_id} has inconsistent architecture")
        analysis_input = _validate_hashed_file(
            analysis_root,
            {
                "path": program.get("analysis_input"),
                "sha256": program.get("analysis_input_sha256"),
            },
            f"analysis program {cpu_id} input",
        )
        if space == "snes-rom":
            if cpu_id != "w65c816" or program.get("status") != "independent-state-analysis":
                raise ContractError("SNES main program identity is invalid")
            if analysis_input.stat().st_size != rom_size or _sha256(analysis_input) != rom_sha:
                raise ContractError("SNES main analysis input differs from cartridge ROM")
            main_payload = analysis_input.read_bytes()
            state_path = _validate_hashed_file(
                analysis_root,
                {
                    "path": program.get("instructions"),
                    "sha256": program.get("instructions_sha256"),
                },
                "W65C816 state instructions",
            )
            state = _read_json_artifact(state_path, "W65C816 state instructions")
            if (
                state.get("schema") != "retrolarium.snes.state-analysis"
                or state.get("input_sha256") != rom_sha
                or len(state.get("instructions", [])) != program.get("instruction_count")
            ):
                raise ContractError("invalid W65C816 state instruction artifact")
        else:
            edge = program.get("derived_from")
            if not isinstance(edge, str) or not edge:
                raise ContractError(f"SPC700 program {cpu_id} has no derivation")
            derived_edges.add(edge)
            if program.get("status") not in {"extracted", "analyzed"}:
                raise ContractError(f"SPC700 program {cpu_id} has invalid status")
            if program.get("status") == "analyzed":
                for field, hash_field in (
                    ("instructions", "instructions_sha256"),
                    ("raw_facts", "raw_facts_sha256"),
                    ("report", "report_sha256"),
                ):
                    _validate_hashed_file(
                        analysis_root,
                        {"path": program.get(field), "sha256": program.get(hash_field)},
                        f"SPC700 program {cpu_id} {field}",
                    )
    if main_payload is None:
        raise ContractError("SNES analysis has no W65C816 program")

    pointers = records["pointers"][1]
    symbols = records["symbols"][1]
    for value, schema, name in (
        (pointers, "retrolarium.snes.pointers", "pointers"),
        (symbols, "retrolarium.symbols", "symbols"),
    ):
        if value.get("schema") != schema or value.get("schema_version") != 1:
            raise ContractError(f"unsupported SNES {name} artifact")
        if value.get("input_sha256") != rom_sha:
            raise ContractError(f"SNES {name} input differs from project input")

    evidence = records["cross_cpu_evidence"][1]
    if (
        evidence.get("schema") != "retrolarium.cross-cpu-evidence"
        or evidence.get("schema_version") != 1
        or evidence.get("platform") != "snes"
        or evidence.get("input_sha256") != container_sha
    ):
        raise ContractError("unsupported SNES cross-CPU evidence artifact")
    edges = evidence.get("edges")
    if not isinstance(edges, list) or manifest["cross_cpu_evidence"].get("edge_count") != len(edges):
        raise ContractError("SNES cross-CPU edge count is invalid")
    edge_ids: set[str] = set()
    for index, value in enumerate(edges):
        edge = _mapping(value, f"cross_cpu_evidence.edges[{index}]")
        source = _mapping(edge.get("source"), f"edge {index} source")
        target = _mapping(edge.get("target"), f"edge {index} target")
        edge_id = edge.get("id")
        size = edge.get("size")
        physical_start = source.get("physical_start")
        physical_end = source.get("physical_end")
        target_start = target.get("start")
        target_end = target.get("end")
        if (
            not isinstance(edge_id, str)
            or not edge_id
            or edge_id in edge_ids
            or edge.get("kind") != "memory_copy"
            or edge.get("confidence") != "proven-static-copy"
            or source.get("cpu_id") != "w65c816"
            or source.get("address_space") != "snes-rom"
            or target.get("cpu_id") != "spc700"
            or target.get("address_space") != "spc700-ram"
            or not isinstance(size, int)
            or size <= 0
            or not isinstance(physical_start, int)
            or not isinstance(physical_end, int)
            or physical_end - physical_start + 1 != size
            or physical_start < 0
            or physical_end >= len(main_payload)
            or not isinstance(target_start, int)
            or not isinstance(target_end, int)
            or target_end - target_start + 1 != size
        ):
            raise ContractError(f"invalid SNES cross-CPU edge at index {index}")
        payload = _validate_hashed_file(
            analysis_root,
            {"path": edge.get("payload"), "sha256": edge.get("payload_sha256")},
            f"SNES cross-CPU edge {edge_id} payload",
        ).read_bytes()
        if payload != main_payload[physical_start:physical_end + 1]:
            raise ContractError(f"SNES cross-CPU edge {edge_id} payload is not its ROM slice")
        edge_ids.add(edge_id)
    if derived_edges != edge_ids:
        raise ContractError("SPC700 programs and cross-CPU evidence do not correspond")

    assets = _mapping(manifest.get("assets"), "assets")
    if assets.get("schema") != "retrolarium.assets" or assets.get("schema_version") != 1:
        raise ContractError("unsupported SNES assets manifest")
    items = assets.get("items")
    if not isinstance(items, list):
        raise ContractError("SNES assets.items must be an array")
    asset_derivations: set[str] = set()
    for index, value in enumerate(items):
        item = _mapping(value, f"assets.items[{index}]")
        path = _validate_hashed_file(root, item, f"SNES asset {index}")
        if path.stat().st_size != item.get("size") or item.get("kind") != "spc700-program":
            raise ContractError(f"invalid SNES asset at index {index}")
        edge = item.get("derived_from")
        if not isinstance(edge, str):
            raise ContractError(f"SNES asset {index} has no derivation")
        asset_derivations.add(edge)
    if asset_derivations != edge_ids:
        raise ContractError("SNES assets and cross-CPU evidence do not correspond")

    source = _mapping(manifest.get("source"), "source")
    if source.get("dialect") != "ca65" or source.get("whole_rom_fallback") is not False:
        raise ContractError("unsupported SNES source policy")
    units = source.get("units")
    if not isinstance(units, list) or not units:
        raise ContractError("SNES source.units must be a non-empty list")
    for unit in units:
        if not artifact_path(root, unit).is_file():
            raise ContractError("SNES source unit does not exist")
    _validate_hashed_file(root, _mapping(source.get("emission"), "source.emission"), "emission")
    coverage = _mapping(source.get("coverage"), "source.coverage")
    categories = (
        "instruction_bytes", "instruction_fallback_bytes", "pointer_bytes",
        "header_bytes", "raw_bytes",
    )
    if (
        coverage.get("rom_bytes") != rom_size
        or coverage.get("copier_header_bytes") != copier_size
        or any(not isinstance(coverage.get(name), int) or coverage[name] < 0 for name in categories)
        or sum(coverage[name] for name in categories) != rom_size
    ):
        raise ContractError("SNES source coverage does not partition the ROM")

    operations = _mapping(manifest.get("operations"), "operations")
    build = _mapping(operations.get("build"), "operations.build")
    verify = _mapping(operations.get("verify"), "operations.verify")
    launch = _mapping(operations.get("launch"), "operations.launch")
    if (
        build.get("id") != "retrolarium.project.build"
        or build.get("runner") not in {"docker", "retrolarium-kit"}
        or build.get("argv") != ["make", "all"]
        or not artifact_path(root, build.get("project_directory")).is_dir()
        or build.get("output") != verify.get("artifact")
        or build.get("output") != launch.get("artifact")
        or verify.get("id") != "retrolarium.project.verify"
        or verify.get("expected_sha256") != container_sha
        or verify.get("expected_size") != container_size
        or launch.get("id") != "retrolarium.project.launch"
        or launch.get("platform") != "snes"
        or launch.get("default_machine") != "snes"
        or launch.get("supported_machines") != ["snes", "snespal"]
        or launch.get("supported_modes") != ["interactive-plan", "smoke"]
    ):
        raise ContractError("invalid SNES project operation contract")
    _validate_build_runner(
        root, build, suite="nes", recipe="ca65-ld65-v1"
    )

    verification = _mapping(manifest.get("verification"), "verification")
    if verify_rebuilt and verification.get("status") == "exact":
        rebuilt = artifact_path(root, verify.get("artifact"))
        if (
            not rebuilt.is_file()
            or rebuilt.stat().st_size != container_size
            or _sha256(rebuilt) != container_sha
            or verification.get("original_sha256") != container_sha
            or verification.get("rebuilt_sha256") != container_sha
        ):
            raise ContractError("rebuilt SNES ROM no longer matches exact verification")


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
    elif schema == "retrolarium.snes.disassembly":
        validate_snes_disassembly_manifest(
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
