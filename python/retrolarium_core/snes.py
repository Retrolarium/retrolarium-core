"""Strict SNES cartridge parsing and 24-bit LoROM/HiROM projections."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path


class SnesError(ValueError):
    """The input is not a supported plain LoROM or HiROM cartridge image."""


@dataclass(frozen=True)
class SnesHeader:
    title: str
    map_mode_byte: int
    map_mode: str
    speed: str
    chipset: int
    rom_size_code: int
    ram_size_code: int
    region_code: int
    developer_id: int
    version: int
    checksum_complement: int
    checksum: int

    @property
    def declared_rom_size(self) -> int:
        return 1 << (self.rom_size_code + 10)

    @property
    def declared_ram_size(self) -> int:
        return 0 if self.ram_size_code == 0 else 1 << (self.ram_size_code + 10)


@dataclass(frozen=True)
class SnesVector:
    mode: str
    index: int
    name: str
    raw_value: int
    cpu_address: int | None
    rom_offset: int | None


@dataclass(frozen=True)
class SnesRegion:
    name: str
    container_offset: int
    rom_offset: int | None
    size: int
    sha256: str


@dataclass(frozen=True)
class SnesBusWindow:
    name: str
    kind: str
    bank_start: int
    bank_end: int
    address_start: int
    address_end: int


@dataclass(frozen=True)
class SnesImage:
    source: Path | None
    container_data: bytes
    copier_header: bytes
    data: bytes
    header_offset: int
    header_data: bytes
    header: SnesHeader
    vector_table: tuple[SnesVector, ...]
    computed_checksum: int
    checksum_status: str
    sha256: str
    rom_sha256: str
    warnings: tuple[str, ...]

    @property
    def copier_header_size(self) -> int:
        return len(self.copier_header)

    @property
    def reset_vector(self) -> SnesVector:
        return next(
            vector
            for vector in self.vector_table
            if vector.mode == "emulation" and vector.name == "reset"
        )

    @property
    def regions(self) -> tuple[SnesRegion, ...]:
        regions: list[SnesRegion] = []
        if self.copier_header:
            regions.append(
                _region("copier_header", 0, None, self.copier_header)
            )
        container_base = self.copier_header_size
        if self.header_offset:
            regions.append(
                _region(
                    "rom_before_internal_header",
                    container_base,
                    0,
                    self.data[: self.header_offset],
                )
            )
        regions.append(
            _region(
                "internal_header_and_vectors",
                container_base + self.header_offset,
                self.header_offset,
                self.header_data,
            )
        )
        tail = self.header_offset + 0x40
        if tail < len(self.data):
            regions.append(
                _region(
                    "rom_after_internal_header",
                    container_base + tail,
                    tail,
                    self.data[tail:],
                )
            )
        return tuple(regions)

    @property
    def bus_windows(self) -> tuple[SnesBusWindow, ...]:
        windows = [
            SnesBusWindow("wram", "wram", 0x7E, 0x7F, 0, 0xFFFF),
            SnesBusWindow("wram_mirror_00", "wram", 0, 0x3F, 0, 0x1FFF),
            SnesBusWindow("wram_mirror_80", "wram", 0x80, 0xBF, 0, 0x1FFF),
        ]
        if self.header.map_mode == "lorom":
            windows.extend(
                (
                    SnesBusWindow("rom_00", "rom", 0, 0x3F, 0x8000, 0xFFFF),
                    SnesBusWindow("rom_40", "rom", 0x40, 0x6F, 0, 0xFFFF),
                    SnesBusWindow("rom_70", "rom", 0x70, 0x7D, 0x8000, 0xFFFF),
                    SnesBusWindow("rom_80", "rom", 0x80, 0xBF, 0x8000, 0xFFFF),
                    SnesBusWindow("rom_c0", "rom", 0xC0, 0xEF, 0, 0xFFFF),
                    SnesBusWindow("rom_f0", "rom", 0xF0, 0xFF, 0x8000, 0xFFFF),
                )
            )
        else:
            windows.extend(
                (
                    SnesBusWindow("rom_00", "rom", 0, 0x3F, 0x8000, 0xFFFF),
                    SnesBusWindow("rom_40", "rom", 0x40, 0x7D, 0, 0xFFFF),
                    SnesBusWindow("rom_80", "rom", 0x80, 0xBF, 0x8000, 0xFFFF),
                    SnesBusWindow("rom_c0", "rom", 0xC0, 0xFF, 0, 0xFFFF),
                )
            )
        if self.header.declared_ram_size:
            if self.header.map_mode == "lorom":
                windows.extend(
                    (
                        SnesBusWindow("sram_70", "sram", 0x70, 0x7D, 0, 0x7FFF),
                        SnesBusWindow("sram_f0", "sram", 0xF0, 0xFF, 0, 0x7FFF),
                    )
                )
            else:
                windows.extend(
                    (
                        SnesBusWindow("sram_20", "sram", 0x20, 0x3F, 0x6000, 0x7FFF),
                        SnesBusWindow("sram_a0", "sram", 0xA0, 0xBF, 0x6000, 0x7FFF),
                    )
                )
        return tuple(windows)


HEADER_SIZE = 0x40
LOROM_HEADER_OFFSET = 0x7FC0
HIROM_HEADER_OFFSET = 0xFFC0
MAX_STANDARD_ROM_SIZE = 0x400000
STANDARD_MAP_MODES = {
    0x20: ("lorom", "slow"),
    0x21: ("hirom", "slow"),
    0x30: ("lorom", "fast"),
    0x31: ("hirom", "fast"),
}
EX_LOROM_MAP_MODES = {0x32}
EX_HIROM_MAP_MODES = {0x25, 0x35}
ENHANCEMENT_MAP_MODES = {0x22, 0x23, 0x33}
PLAIN_CHIPSETS = {0x00, 0x01, 0x02}

NATIVE_VECTOR_NAMES = (
    "reserved_native_0",
    "reserved_native_1",
    "cop",
    "brk",
    "abort",
    "nmi",
    "reserved_native_6",
    "irq",
)
EMULATION_VECTOR_NAMES = (
    "reserved_emulation_0",
    "reserved_emulation_1",
    "cop",
    "reserved_emulation_3",
    "abort",
    "nmi",
    "reset",
    "irq_brk",
)


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _region(
    name: str,
    container_offset: int,
    rom_offset: int | None,
    payload: bytes,
) -> SnesRegion:
    return SnesRegion(
        name, container_offset, rom_offset, len(payload), _digest(payload)
    )


def _u16le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def _text(data: bytes, start: int, end: int) -> str:
    return data[start:end].decode("ascii", errors="replace").rstrip(" \0")


def _mirror_sum(data: bytes, mask: int) -> int:
    """Sum a non-power-of-two image as mirrored into its next decode window."""
    while mask and not (len(data) & mask):
        mask >>= 1
    if not mask:
        return 0
    total = sum(data[:mask])
    remainder = data[mask:]
    if remainder:
        remainder_sum = _mirror_sum(remainder, mask >> 1)
        remainder_size = 1 << (len(remainder) - 1).bit_length()
        total += remainder_sum * (mask // remainder_size)
    return total


def cartridge_checksum(data: bytes) -> int:
    """Return the SNES mirrored 16-bit byte checksum for headerless ROM data."""
    if not data:
        return 0
    mask = 1 << (len(data).bit_length() - 1)
    return _mirror_sum(data, mask) & 0xFFFF


def _header_score(data: bytes, offset: int) -> int:
    if offset + HEADER_SIZE > len(data):
        return -1000
    header = data[offset : offset + HEADER_SIZE]
    map_mode = header[0x15]
    expected = (
        "lorom" if offset == LOROM_HEADER_OFFSET else "hirom"
    )
    actual = STANDARD_MAP_MODES.get(map_mode, (None, None))[0]
    if map_mode in ENHANCEMENT_MAP_MODES or map_mode in EX_LOROM_MAP_MODES:
        actual = "lorom"
    elif map_mode in EX_HIROM_MAP_MODES:
        actual = "hirom"
    score = 0
    score += 12 if actual == expected else -16
    checksum_complement = _u16le(header, 0x1C)
    checksum = _u16le(header, 0x1E)
    if checksum or checksum_complement:
        score += 8 if (checksum ^ checksum_complement) == 0xFFFF else -8
    reset = _u16le(header, 0x3C)
    score += 8 if reset >= 0x8000 else -12
    title = header[:21]
    score += 4 if all(value == 0 or 0x20 <= value <= 0x7E for value in title) else -4
    rom_size_code = header[0x17]
    score += 2 if 5 <= rom_size_code <= 12 else -2
    return score


def _select_header(data: bytes) -> int:
    scores = {
        offset: _header_score(data, offset)
        for offset in (LOROM_HEADER_OFFSET, HIROM_HEADER_OFFSET)
        if offset + HEADER_SIZE <= len(data)
    }
    if not scores:
        raise SnesError("ROM is too small to contain a LoROM or HiROM header")
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if ordered[0][1] < 10:
        raise SnesError(
            "no plausible SNES internal header at LoROM or HiROM offset"
        )
    if len(ordered) > 1 and ordered[0][1] == ordered[1][1]:
        raise SnesError("LoROM and HiROM header candidates are ambiguous")
    return ordered[0][0]


def _parse_header(data: bytes, offset: int) -> SnesHeader:
    raw = data[offset : offset + HEADER_SIZE]
    map_mode_byte = raw[0x15]
    if map_mode_byte in EX_HIROM_MAP_MODES:
        raise SnesError(
            f"ExHiROM map mode 0x{map_mode_byte:02X} is not supported by v1"
        )
    if map_mode_byte in EX_LOROM_MAP_MODES:
        raise SnesError(
            f"ExLoROM map mode 0x{map_mode_byte:02X} is not supported by v1"
        )
    if map_mode_byte in ENHANCEMENT_MAP_MODES:
        raise SnesError(
            f"enhancement-chip map mode 0x{map_mode_byte:02X} is not supported"
        )
    mapping = STANDARD_MAP_MODES.get(map_mode_byte)
    if mapping is None:
        raise SnesError(f"unsupported SNES map mode 0x{map_mode_byte:02X}")
    expected = "lorom" if offset == LOROM_HEADER_OFFSET else "hirom"
    if mapping[0] != expected:
        raise SnesError(
            f"header location implies {expected}, map byte implies {mapping[0]}"
        )
    chipset = raw[0x16]
    if chipset not in PLAIN_CHIPSETS:
        raise SnesError(
            f"enhancement chipset 0x{chipset:02X} is not supported by v1"
        )
    return SnesHeader(
        title=_text(raw, 0, 21),
        map_mode_byte=map_mode_byte,
        map_mode=mapping[0],
        speed=mapping[1],
        chipset=chipset,
        rom_size_code=raw[0x17],
        ram_size_code=raw[0x18],
        region_code=raw[0x19],
        developer_id=raw[0x1A],
        version=raw[0x1B],
        checksum_complement=_u16le(raw, 0x1C),
        checksum=_u16le(raw, 0x1E),
    )


def _linear_rom_offset(map_mode: str, address: int) -> int:
    if not 0 <= address <= 0xFFFFFF:
        raise SnesError(f"CPU address 0x{address:X} exceeds 24 bits")
    bank = address >> 16
    offset = address & 0xFFFF
    if bank in {0x7E, 0x7F}:
        raise SnesError(f"CPU address 0x{address:06X} is work RAM, not ROM")
    if map_mode == "lorom":
        bank_without_mirror = bank & 0x7F
        full_bank_window = 0x40 <= bank_without_mirror <= 0x6F
        if offset < 0x8000 and not full_bank_window:
            raise SnesError(f"CPU address 0x{address:06X} is not in a LoROM window")
        return bank_without_mirror * 0x8000 + (offset & 0x7FFF)
    bank_without_mirror = bank & 0x3F
    full_bank_window = 0x40 <= bank <= 0x7D or 0xC0 <= bank <= 0xFF
    if offset < 0x8000 and not full_bank_window:
        raise SnesError(f"CPU address 0x{address:06X} is not in a HiROM window")
    return bank_without_mirror * 0x10000 + offset


def _mirror_offset(offset: int, size: int) -> int:
    if size <= 0:
        raise SnesError("cannot mirror into an empty ROM")
    if offset < size:
        return offset
    mask = 1 << (offset.bit_length() - 1)
    base = 0
    remaining = size
    while offset >= remaining:
        while mask and not (offset & mask):
            mask >>= 1
        if not mask:
            raise SnesError("cannot resolve mirrored ROM offset")
        offset -= mask
        if remaining > mask:
            remaining -= mask
            base += mask
        mask >>= 1
    return base + offset


def snes_to_rom_offset(image: SnesImage, address: int) -> int:
    """Map a 24-bit CPU address through LoROM/HiROM and cartridge mirroring."""
    linear = _linear_rom_offset(image.header.map_mode, address)
    return _mirror_offset(linear, len(image.data))


def snes_to_wram_offset(address: int) -> int:
    """Map a full WRAM window or low-bank WRAM mirror to 128 KiB WRAM."""
    if not 0 <= address <= 0xFFFFFF:
        raise SnesError(f"CPU address 0x{address:X} exceeds 24 bits")
    bank = address >> 16
    offset = address & 0xFFFF
    if bank in {0x7E, 0x7F}:
        return (bank - 0x7E) * 0x10000 + offset
    if (bank <= 0x3F or 0x80 <= bank <= 0xBF) and offset <= 0x1FFF:
        return offset
    raise SnesError(f"CPU address 0x{address:06X} is not in a WRAM window")


def snes_to_sram_offset(image: SnesImage, address: int) -> int:
    """Map a standard plain LoROM/HiROM SRAM window to save-RAM storage."""
    size = image.header.declared_ram_size
    if not size:
        raise SnesError("cartridge header declares no save RAM")
    if not 0 <= address <= 0xFFFFFF:
        raise SnesError(f"CPU address 0x{address:X} exceeds 24 bits")
    bank = address >> 16
    offset = address & 0xFFFF
    if image.header.map_mode == "lorom":
        if not (0x70 <= bank <= 0x7D or 0xF0 <= bank <= 0xFF) or offset >= 0x8000:
            raise SnesError(f"CPU address 0x{address:06X} is not in a LoROM SRAM window")
        linear = ((bank & 0x0F) << 15) | offset
    else:
        if not (0x20 <= bank <= 0x3F or 0xA0 <= bank <= 0xBF) or not 0x6000 <= offset <= 0x7FFF:
            raise SnesError(f"CPU address 0x{address:06X} is not in a HiROM SRAM window")
        linear = ((bank & 0x1F) << 13) | (offset - 0x6000)
    return linear % size


def rom_offset_to_snes(image: SnesImage, offset: int) -> int:
    """Return one canonical CPU address for a physical ROM byte."""
    if not 0 <= offset < len(image.data):
        raise SnesError(f"ROM offset 0x{offset:X} is outside the image")
    if image.header.map_mode == "lorom":
        bank = offset // 0x8000
        if bank in {0x7E, 0x7F}:
            bank |= 0x80
        return (bank << 16) | 0x8000 | (offset & 0x7FFF)
    return ((0xC0 + offset // 0x10000) << 16) | (offset & 0xFFFF)


def rom_offset_aliases(image: SnesImage, offset: int) -> tuple[int, ...]:
    """Return direct standard bus aliases, excluding size-induced mirrors."""
    canonical = rom_offset_to_snes(image, offset)
    aliases: set[int] = {canonical}
    if image.header.map_mode == "lorom":
        bank = offset // 0x8000
        within = offset & 0x7FFF
        if bank not in {0x7E, 0x7F}:
            aliases.add((bank << 16) | 0x8000 | within)
            aliases.add(((bank | 0x80) << 16) | 0x8000 | within)
        if 0x40 <= bank <= 0x6F:
            aliases.add((bank << 16) | within)
            aliases.add(((bank | 0x80) << 16) | within)
    else:
        bank = offset // 0x10000
        within = offset & 0xFFFF
        aliases.add(((0x40 + bank) << 16) | within)
        aliases.add(((0xC0 + bank) << 16) | within)
        if within >= 0x8000:
            aliases.add((bank << 16) | within)
            aliases.add(((0x80 + bank) << 16) | within)
    return tuple(sorted(aliases))


def _parse_vectors(
    data: bytes, image_header_offset: int, map_mode: str
) -> tuple[SnesVector, ...]:
    vectors: list[SnesVector] = []
    for mode, start, names in (
        ("native", 0x20, NATIVE_VECTOR_NAMES),
        ("emulation", 0x30, EMULATION_VECTOR_NAMES),
    ):
        for index, name in enumerate(names):
            raw = _u16le(data, image_header_offset + start + index * 2)
            cpu_address = raw if raw >= 0x8000 else None
            rom_offset: int | None = None
            if cpu_address is not None:
                try:
                    linear = _linear_rom_offset(map_mode, cpu_address)
                    rom_offset = _mirror_offset(linear, len(data))
                except SnesError:
                    cpu_address = None
            vectors.append(
                SnesVector(mode, index, name, raw, cpu_address, rom_offset)
            )
    return tuple(vectors)


def parse_snes(container_data: bytes, source: Path | None = None) -> SnesImage:
    remainder = len(container_data) % 0x8000
    if remainder == 0x200:
        copier_header = container_data[:0x200]
        data = container_data[0x200:]
    elif remainder == 0:
        copier_header = b""
        data = container_data
    else:
        raise SnesError(
            f"container size {len(container_data)} is not a 32 KiB ROM multiple "
            "with an optional 512-byte copier header"
        )
    if len(data) < 0x8000:
        raise SnesError("SNES ROM must contain at least one 32 KiB bank")
    if len(data) > MAX_STANDARD_ROM_SIZE:
        raise SnesError(
            "ROM exceeds 4 MiB; ExLoROM/ExHiROM are not supported by v1"
        )
    header_offset = _select_header(data)
    header = _parse_header(data, header_offset)
    vectors = _parse_vectors(data, header_offset, header.map_mode)
    reset = next(
        vector
        for vector in vectors
        if vector.mode == "emulation" and vector.name == "reset"
    )
    if reset.cpu_address is None or reset.rom_offset is None:
        raise SnesError(
            f"emulation RESET vector 0x{reset.raw_value:04X} is not backed by ROM"
        )
    computed = cartridge_checksum(data)
    pair_valid = (header.checksum ^ header.checksum_complement) == 0xFFFF
    if header.checksum == 0 and header.checksum_complement == 0:
        checksum_status = "absent"
    elif not pair_valid:
        checksum_status = "invalid-pair"
    elif header.checksum == computed:
        checksum_status = "valid"
    else:
        checksum_status = "mismatch"
    warnings: list[str] = []
    if header.declared_rom_size != len(data):
        warnings.append(
            f"declared ROM size {header.declared_rom_size} differs from "
            f"file-backed size {len(data)}"
        )
    if checksum_status != "valid":
        warnings.append(
            f"cartridge checksum status is {checksum_status}; stored "
            f"0x{header.checksum:04X}, computed 0x{computed:04X}"
        )
    return SnesImage(
        source=source,
        container_data=container_data,
        copier_header=copier_header,
        data=data,
        header_offset=header_offset,
        header_data=data[header_offset : header_offset + HEADER_SIZE],
        header=header,
        vector_table=vectors,
        computed_checksum=computed,
        checksum_status=checksum_status,
        sha256=_digest(container_data),
        rom_sha256=_digest(data),
        warnings=tuple(warnings),
    )


def load_snes(path: Path) -> SnesImage:
    return parse_snes(path.read_bytes(), path.resolve())


def image_manifest(image: SnesImage) -> dict[str, object]:
    header = image.header
    return {
        "schema": "retrolarium.snes.image",
        "schema_version": 1,
        "source": str(image.source) if image.source is not None else None,
        "container_size": len(image.container_data),
        "container_sha256": image.sha256,
        "copier_header_size": image.copier_header_size,
        "rom_size": len(image.data),
        "rom_sha256": image.rom_sha256,
        "cpu": "w65c816",
        "byte_order": "little",
        "mapping": header.map_mode,
        "header_offset": image.header_offset,
        "header": {
            "title": header.title,
            "map_mode_byte": header.map_mode_byte,
            "map_mode": header.map_mode,
            "speed": header.speed,
            "chipset": header.chipset,
            "rom_size_code": header.rom_size_code,
            "declared_rom_size": header.declared_rom_size,
            "ram_size_code": header.ram_size_code,
            "declared_ram_size": header.declared_ram_size,
            "region_code": header.region_code,
            "developer_id": header.developer_id,
            "version": header.version,
            "checksum_complement": header.checksum_complement,
            "checksum": header.checksum,
            "computed_checksum": image.computed_checksum,
            "checksum_status": image.checksum_status,
        },
        "reset_vector": image.reset_vector.raw_value,
        "reset_address": image.reset_vector.cpu_address,
        "reset_rom_offset": image.reset_vector.rom_offset,
        "regions": [
            {
                "name": region.name,
                "container_offset": region.container_offset,
                "rom_offset": region.rom_offset,
                "size": region.size,
                "sha256": region.sha256,
            }
            for region in image.regions
        ],
        "bus_windows": [
            {
                "name": window.name,
                "kind": window.kind,
                "bank_start": window.bank_start,
                "bank_end": window.bank_end,
                "address_start": window.address_start,
                "address_end": window.address_end,
            }
            for window in image.bus_windows
        ],
        "vectors": [
            {
                "mode": vector.mode,
                "index": vector.index,
                "name": vector.name,
                "raw_value": vector.raw_value,
                "cpu_address": vector.cpu_address,
                "rom_offset": vector.rom_offset,
            }
            for vector in image.vector_table
        ],
        "warnings": list(image.warnings),
    }
