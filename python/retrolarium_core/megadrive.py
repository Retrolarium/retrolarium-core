"""Strict Sega Mega Drive cartridge parsing and 68000 address projection."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path


class MegaDriveError(ValueError):
    """The input is not a Mega Drive cartridge image supported by the kit."""


@dataclass(frozen=True)
class ImageRegion:
    name: str
    file_offset: int
    size: int
    sha256: str


@dataclass(frozen=True)
class AddressRange:
    name: str
    cpu_space: str
    cpu_start: int
    cpu_end: int
    file_offset: int | None


@dataclass(frozen=True)
class CartridgeHeader:
    system: str
    copyright: str
    domestic_title: str
    overseas_title: str
    product_code: str
    checksum: int
    io_support: str
    rom_start: int
    rom_end: int
    ram_start: int
    ram_end: int
    modem: str
    memo: str
    regions: str


@dataclass(frozen=True)
class M68kVector:
    index: int
    name: str
    raw_value: int
    address: int


@dataclass(frozen=True)
class MegaDriveImage:
    source: Path | None
    data: bytes
    vectors: bytes
    header_data: bytes
    payload: bytes
    header: CartridgeHeader
    vector_table: tuple[M68kVector, ...]
    computed_checksum: int
    checksum_status: str
    sha256: str
    warnings: tuple[str, ...]

    @property
    def initial_stack_pointer(self) -> int:
        return self.vector_table[0].raw_value

    @property
    def reset_vector(self) -> int:
        return self.vector_table[1].raw_value

    @property
    def reset_address(self) -> int:
        return self.vector_table[1].address

    @property
    def actual_rom_end(self) -> int:
        return self.header.rom_start + len(self.data) - 1

    @property
    def regions(self) -> tuple[ImageRegion, ...]:
        return (
            _region("vectors", 0, self.vectors),
            _region("header", 0x100, self.header_data),
            _region("payload", 0x200, self.payload),
        )

    @property
    def address_ranges(self) -> tuple[AddressRange, ...]:
        return (
            AddressRange(
                name="cartridge_rom",
                cpu_space="m68k",
                cpu_start=self.header.rom_start,
                cpu_end=self.actual_rom_end,
                file_offset=0,
            ),
            AddressRange(
                name="work_ram",
                cpu_space="m68k",
                cpu_start=self.header.ram_start,
                cpu_end=self.header.ram_end,
                file_offset=None,
            ),
        )


VECTOR_NAMES = (
    "initial_ssp",
    "reset",
    "bus_error",
    "address_error",
    "illegal_instruction",
    "division_by_zero",
    "chk",
    "trapv",
    "privilege_violation",
    "trace",
    "line_1010",
    "line_1111",
    "reserved_12",
    "reserved_13",
    "reserved_14",
    "uninitialized_interrupt",
    *(f"reserved_{index}" for index in range(16, 24)),
    "spurious_interrupt",
    *(f"level_{level}_interrupt" for level in range(1, 8)),
    *(f"trap_{number}" for number in range(16)),
    *(f"reserved_{index}" for index in range(48, 64)),
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _region(name: str, offset: int, payload: bytes) -> ImageRegion:
    return ImageRegion(name, offset, len(payload), _digest(payload))


def _u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 2], "big")


def _u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 4], "big")


def _text(data: bytes, start: int, end: int) -> str:
    return data[start:end].decode("ascii", errors="replace").rstrip(" \0")


def cartridge_checksum(data: bytes, end: int | None = None) -> int:
    """Return the standard 16-bit big-endian sum from file offset 0x200 to
    `end` (the end of the file by default)."""
    total = 0
    for offset in range(0x200, len(data) if end is None else min(end, len(data)), 2):
        word = data[offset:offset + 2]
        if len(word) == 1:
            word += b"\0"
        total = (total + int.from_bytes(word, "big")) & 0xFFFF
    return total


def stamp_cartridge_checksum(data: bytes) -> bytes:
    """Return a ROM with the Sega header checksum matching its payload."""
    if len(data) < 0x200 or data[0x100:0x104] != b"SEGA":
        raise MegaDriveError("cannot stamp a non-Mega Drive cartridge image")
    stamped = bytearray(data)
    # The boot code sums up to the ROM end the header gives: padding past it
    # (or a file cut short of it) does not count.
    rom_end = int.from_bytes(data[0x1A4:0x1A8], "big")
    end = rom_end + 1 if 0x200 < rom_end < len(data) else None
    stamped[0x18E:0x190] = cartridge_checksum(data, end).to_bytes(2, "big")
    return bytes(stamped)


def _parse_header(data: bytes) -> CartridgeHeader:
    return CartridgeHeader(
        system=_text(data, 0x100, 0x110),
        copyright=_text(data, 0x110, 0x120),
        domestic_title=_text(data, 0x120, 0x150),
        overseas_title=_text(data, 0x150, 0x180),
        product_code=_text(data, 0x180, 0x18E),
        checksum=_u16(data, 0x18E),
        io_support=_text(data, 0x190, 0x1A0),
        rom_start=_u32(data, 0x1A0),
        rom_end=_u32(data, 0x1A4),
        ram_start=_u32(data, 0x1A8),
        ram_end=_u32(data, 0x1AC),
        modem=_text(data, 0x1BC, 0x1C8),
        memo=_text(data, 0x1C8, 0x1F0),
        regions=_text(data, 0x1F0, 0x200),
    )


def parse_megadrive(data: bytes, source: Path | None = None) -> MegaDriveImage:
    if len(data) < 0x200:
        raise MegaDriveError(
            f"image is {len(data)} bytes; a cartridge header needs at least 512"
        )
    if not data[0x100:0x110].startswith(b"SEGA"):
        raise MegaDriveError("missing SEGA cartridge signature at file offset 0x100")

    header = _parse_header(data)
    if header.rom_start > header.rom_end:
        raise MegaDriveError("declared ROM range is reversed")
    if header.ram_start > header.ram_end:
        raise MegaDriveError("declared RAM range is reversed")
    if header.rom_end > 0xFFFFFF or header.ram_end > 0xFFFFFF:
        raise MegaDriveError("declared range exceeds the 68000 24-bit address space")

    actual_rom_end = header.rom_start + len(data) - 1
    if actual_rom_end > 0xFFFFFF:
        raise MegaDriveError("file-backed ROM exceeds the 68000 24-bit address space")
    vector_table = tuple(
        M68kVector(
            index=index,
            name=VECTOR_NAMES[index],
            raw_value=(raw_value := _u32(data, index * 4)),
            address=raw_value & 0xFFFFFF,
        )
        for index in range(64)
    )
    reset_vector = vector_table[1]
    if reset_vector.address & 1:
        raise MegaDriveError(
            f"reset vector is odd: 0x{reset_vector.raw_value:08X}"
        )
    if not header.rom_start <= reset_vector.address <= actual_rom_end:
        raise MegaDriveError(
            f"reset vector 0x{reset_vector.raw_value:08X} resolves outside "
            "the file-backed ROM range"
        )

    computed_checksum = cartridge_checksum(data)
    if header.checksum == 0:
        checksum_status = "absent"
    elif header.checksum == computed_checksum:
        checksum_status = "valid"
    else:
        checksum_status = "mismatch"

    warnings: list[str] = []
    if header.rom_end != actual_rom_end:
        warnings.append(
            "declared ROM end 0x"
            f"{header.rom_end:06X} differs from file-backed end 0x{actual_rom_end:06X}"
        )
    if checksum_status == "absent":
        warnings.append("cartridge checksum is not populated")
    elif checksum_status == "mismatch":
        warnings.append(
            f"cartridge checksum is 0x{header.checksum:04X}; "
            f"computed value is 0x{computed_checksum:04X}"
        )

    return MegaDriveImage(
        source=source,
        data=data,
        vectors=data[:0x100],
        header_data=data[0x100:0x200],
        payload=data[0x200:],
        header=header,
        vector_table=vector_table,
        computed_checksum=computed_checksum,
        checksum_status=checksum_status,
        sha256=_digest(data),
        warnings=tuple(warnings),
    )


def load_megadrive(path: Path) -> MegaDriveImage:
    return parse_megadrive(path.read_bytes(), path.resolve())


def m68k_to_rom_offset(image: MegaDriveImage, address: int) -> int:
    if not image.header.rom_start <= address <= image.actual_rom_end:
        raise MegaDriveError(
            f"m68k address 0x{address:06X} is outside the file-backed ROM range"
        )
    return address - image.header.rom_start


def rom_offset_to_m68k(image: MegaDriveImage, offset: int) -> int:
    if not 0 <= offset < len(image.data):
        raise MegaDriveError(f"ROM offset 0x{offset:X} is outside the image")
    return image.header.rom_start + offset


def image_manifest(image: MegaDriveImage) -> dict[str, object]:
    """Return a JSON-safe, deterministic cartridge inspection record."""
    header = image.header
    return {
        "schema": "retrolarium.megadrive.image",
        "schema_version": 1,
        "source": str(image.source) if image.source is not None else None,
        "size": len(image.data),
        "sha256": image.sha256,
        "cpu": "m68000",
        "byte_order": "big",
        "initial_stack_pointer": image.initial_stack_pointer,
        "reset_vector": image.reset_vector,
        "reset_address": image.reset_address,
        "header": {
            "system": header.system,
            "copyright": header.copyright,
            "domestic_title": header.domestic_title,
            "overseas_title": header.overseas_title,
            "product_code": header.product_code,
            "io_support": header.io_support,
            "regions": header.regions,
            "rom_start": header.rom_start,
            "rom_end": header.rom_end,
            "actual_rom_end": image.actual_rom_end,
            "ram_start": header.ram_start,
            "ram_end": header.ram_end,
            "checksum": header.checksum,
            "computed_checksum": image.computed_checksum,
            "checksum_status": image.checksum_status,
        },
        "regions": [
            {
                "name": item.name,
                "file_offset": item.file_offset,
                "size": item.size,
                "sha256": item.sha256,
            }
            for item in image.regions
        ],
        "address_ranges": [
            {
                "name": item.name,
                "cpu_space": item.cpu_space,
                "cpu_start": item.cpu_start,
                "cpu_end": item.cpu_end,
                "file_offset": item.file_offset,
            }
            for item in image.address_ranges
        ],
        "vectors": [
            {
                "index": item.index,
                "name": item.name,
                "raw_value": item.raw_value,
                "address": item.address,
            }
            for item in image.vector_table
        ],
        "warnings": list(image.warnings),
    }
