"""Strict iNES parsing and data-driven mapper address projections."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path


class InesError(ValueError):
    """The input is not an iNES image supported by the current pipeline."""


@dataclass(frozen=True)
class ImageRegion:
    name: str
    file_offset: int
    size: int
    sha256: str


@dataclass(frozen=True)
class CpuProjection:
    region: str
    physical_start: int
    physical_end: int
    cpu_space: str
    cpu_start: int
    cpu_end: int
    bank: int
    canonical: bool
    selector: str | None


@dataclass(frozen=True)
class MapperProfile:
    profile_id: str
    name: str
    mapper: int
    prg_mode: str
    prg_bank_size: int | None
    prg_window_start: int
    max_prg_banks: int
    chr_bank_size: int
    chr_window_start: int
    max_chr_banks: int
    chr_selectable: bool


@dataclass(frozen=True)
class PrgAnalysisTarget:
    bank: int
    physical_start: int
    physical_end: int
    cpu_start: int
    image: InesImage
    synthesized: bool


@dataclass(frozen=True)
class InesImage:
    source: Path | None
    data: bytes
    header: bytes
    trainer: bytes
    prg: bytes
    chr: bytes
    mapper: int
    mirroring: str
    battery: bool
    sha256: str

    @property
    def regions(self) -> tuple[ImageRegion, ...]:
        offset = 0
        regions = [region("header", offset, self.header)]
        offset += len(self.header)
        if self.trainer:
            regions.append(region("trainer", offset, self.trainer))
            offset += len(self.trainer)
        regions.append(region("prg", offset, self.prg))
        offset += len(self.prg)
        if self.chr:
            regions.append(region("chr", offset, self.chr))
        return tuple(regions)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def region(name: str, offset: int, payload: bytes) -> ImageRegion:
    return ImageRegion(name, offset, len(payload), digest(payload))


def _declared_size(data: bytes) -> int:
    if len(data) < 16 or data[:4] != b"NES\x1a":
        raise InesError("missing iNES magic")
    header = data[:16]
    flags6 = header[6]
    flags7 = header[7]
    if flags7 & 0x0C == 0x08:
        raise InesError("NES 2.0 is not supported by the initial NROM pipeline")
    if header[4] == 0:
        raise InesError("iNES image declares no PRG ROM")

    trainer_size = 512 if flags6 & 0x04 else 0
    prg_size = header[4] * 0x4000
    chr_size = header[5] * 0x2000
    return 16 + trainer_size + prg_size + chr_size


def parse_ines(data: bytes, source: Path | None = None) -> InesImage:
    expected_size = _declared_size(data)
    if len(data) != expected_size:
        raise InesError(f"image size is {len(data)}, header describes {expected_size} bytes")
    header = data[:16]
    flags6 = header[6]
    flags7 = header[7]
    # An old dumper's tag in bytes 12-15 ("DiskDude!") means byte 7 is junk
    # too: emulators then take the low mapper nibble only.
    archaic = any(header[12:16])
    mapper = (flags6 >> 4) | (0 if archaic else flags7 & 0xF0)
    trainer_size = 512 if flags6 & 0x04 else 0
    prg_size = header[4] * 0x4000
    chr_size = header[5] * 0x2000

    cursor = 16
    trainer = data[cursor : cursor + trainer_size]
    cursor += trainer_size
    prg = data[cursor : cursor + prg_size]
    cursor += prg_size
    chr_data = data[cursor : cursor + chr_size]
    if flags6 & 0x08:
        mirroring = "four-screen"
    elif flags6 & 0x01:
        mirroring = "vertical"
    else:
        mirroring = "horizontal"
    return InesImage(
        source=source,
        data=data,
        header=header,
        trainer=trainer,
        prg=prg,
        chr=chr_data,
        mapper=mapper,
        mirroring=mirroring,
        battery=bool(flags6 & 0x02),
        sha256=digest(data),
    )


def parse_ines_prefix(data: bytes, source: Path | None = None) -> tuple[InesImage, bytes]:
    """Parse an iNES image embedded at the start of a larger container."""

    expected_size = _declared_size(data)
    if len(data) < expected_size:
        raise InesError(f"image size is {len(data)}, header describes {expected_size} bytes")
    return parse_ines(data[:expected_size], source), data[expected_size:]


def load_ines(path: Path) -> InesImage:
    return parse_ines(path.read_bytes(), path.resolve())


PROFILE_PATH = Path(__file__).resolve().parent / "profiles" / "nes_mappers.json"


@lru_cache(maxsize=1)
def mapper_profiles() -> dict[int, MapperProfile]:
    try:
        document = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InesError(f"cannot read NES mapper profiles: {exc}") from exc
    if document.get("schema_version") != 1 or not isinstance(document.get("profiles"), dict):
        raise InesError("unsupported NES mapper profile schema")
    profiles: dict[int, MapperProfile] = {}
    try:
        for mapper_text, value in document["profiles"].items():
            mapper = int(mapper_text)
            profiles[mapper] = MapperProfile(
                profile_id=str(value["id"]),
                name=str(value["name"]),
                mapper=mapper,
                prg_mode=str(value["prg_mode"]),
                prg_bank_size=(None if value["prg_bank_size"] is None else int(value["prg_bank_size"])),
                prg_window_start=int(value["prg_window_start"]),
                max_prg_banks=int(value["max_prg_banks"]),
                chr_bank_size=int(value["chr_bank_size"]),
                chr_window_start=int(value["chr_window_start"]),
                max_chr_banks=int(value["max_chr_banks"]),
                chr_selectable=bool(value["chr_selectable"]),
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise InesError("invalid NES mapper profile entry") from exc
    return profiles


def mapper_profile(image: InesImage) -> MapperProfile:
    try:
        return mapper_profiles()[image.mapper]
    except KeyError as exc:
        raise InesError(f"mapper {image.mapper} has no Retrolarium profile") from exc


def _projection(
    region_name: str,
    physical_start: int,
    size: int,
    address_space: str,
    logical_start: int,
    bank: int,
    *,
    canonical: bool = True,
    selector: str | None = None,
) -> CpuProjection:
    return CpuProjection(
        region=region_name,
        physical_start=physical_start,
        physical_end=physical_start + size - 1,
        cpu_space=address_space,
        cpu_start=logical_start,
        cpu_end=logical_start + size - 1,
        bank=bank,
        canonical=canonical,
        selector=selector,
    )


def mapper_projections(image: InesImage) -> tuple[CpuProjection, ...]:
    profile = mapper_profile(image)
    projections: list[CpuProjection] = []
    if profile.prg_mode == "nrom_fixed":
        if len(image.prg) == 0x4000:
            projections.extend(
                (
                    _projection("prg", 0, 0x4000, "cpu", 0xC000, 0),
                    _projection("prg", 0, 0x4000, "cpu", 0x8000, 0, canonical=False),
                )
            )
        elif len(image.prg) == 0x8000:
            projections.append(_projection("prg", 0, 0x8000, "cpu", 0x8000, 0))
        else:
            raise InesError(f"{profile.name} requires 16 or 32 KiB PRG, got {len(image.prg)} bytes")
    elif profile.prg_mode == "selectable_32k":
        bank_size = profile.prg_bank_size
        if bank_size is None or len(image.prg) % bank_size:
            raise InesError(f"{profile.name} PRG is not aligned to its bank size")
        bank_count = len(image.prg) // bank_size
        if not 1 <= bank_count <= profile.max_prg_banks:
            raise InesError(f"{profile.name} supports 1..{profile.max_prg_banks} PRG banks, got {bank_count}")
        for bank in range(bank_count):
            projections.append(
                _projection(
                    "prg",
                    bank * bank_size,
                    bank_size,
                    "cpu",
                    profile.prg_window_start,
                    bank,
                    selector="mapper.prg_bank",
                )
            )
    else:
        raise InesError(f"unsupported PRG projection mode: {profile.prg_mode}")

    if image.chr:
        if len(image.chr) % profile.chr_bank_size:
            raise InesError(f"{profile.name} CHR is not aligned to its bank size")
        bank_count = len(image.chr) // profile.chr_bank_size
        if not 1 <= bank_count <= profile.max_chr_banks:
            raise InesError(f"{profile.name} supports 1..{profile.max_chr_banks} CHR banks, got {bank_count}")
        selector = "mapper.chr_bank" if profile.chr_selectable else None
        for bank in range(bank_count):
            projections.append(
                _projection(
                    "chr",
                    bank * profile.chr_bank_size,
                    profile.chr_bank_size,
                    "ppu",
                    profile.chr_window_start,
                    bank,
                    selector=selector,
                )
            )
    return tuple(projections)


def nrom_projections(image: InesImage) -> tuple[CpuProjection, ...]:
    if image.mapper != 0:
        raise InesError(f"NROM profile requires mapper 0, got mapper {image.mapper}")
    return tuple(projection for projection in mapper_projections(image) if projection.region == "prg")


def canonical_prg_start(image: InesImage, bank: int = 0) -> int:
    for projection in mapper_projections(image):
        if projection.region == "prg" and projection.bank == bank and projection.canonical:
            return projection.cpu_start
    raise InesError(f"mapper {image.mapper} has no canonical PRG bank {bank}")


def address_to_region_offset(
    image: InesImage,
    region: str,
    address_space: str,
    address: int,
    *,
    bank: int | None = None,
) -> int:
    matches = [
        projection
        for projection in mapper_projections(image)
        if projection.region == region
        and projection.cpu_space == address_space
        and projection.cpu_start <= address <= projection.cpu_end
        and (bank is None or projection.bank == bank)
    ]
    if not matches:
        raise InesError(
            f"{address_space} address ${address:04X} is outside mapper {image.mapper} {region.upper()} windows"
        )
    offsets = {projection.physical_start + address - projection.cpu_start for projection in matches}
    if len(offsets) != 1:
        raise InesError(f"{address_space} address ${address:04X} is bank-ambiguous; an explicit bank is required")
    return offsets.pop()


def cpu_to_prg_offset(image: InesImage, address: int, *, bank: int | None = None) -> int:
    return address_to_region_offset(image, "prg", "cpu", address, bank=bank)


def _mapper_zero_analysis_image(image: InesImage, prg: bytes) -> InesImage:
    if len(prg) not in {0x4000, 0x8000}:
        raise InesError(f"analysis staging requires a 16 or 32 KiB PRG window, got {len(prg)}")
    flags6 = image.header[6] & 0x0B
    header = b"NES\x1a" + bytes((len(prg) // 0x4000, 0, flags6, 0)) + bytes(8)
    return parse_ines(header + prg)


def prg_analysis_targets(image: InesImage) -> tuple[PrgAnalysisTarget, ...]:
    """Materialize non-overlapping mapper-0 views for external code analyzers."""
    projections = tuple(
        projection for projection in mapper_projections(image) if projection.region == "prg" and projection.canonical
    )
    targets: list[PrgAnalysisTarget] = []
    for projection in projections:
        if image.mapper == 0 and len(projections) == 1:
            analysis_image = image
            synthesized = False
        else:
            prg = image.prg[projection.physical_start : projection.physical_end + 1]
            analysis_image = _mapper_zero_analysis_image(image, prg)
            synthesized = True
        targets.append(
            PrgAnalysisTarget(
                bank=projection.bank,
                physical_start=projection.physical_start,
                physical_end=projection.physical_end,
                cpu_start=projection.cpu_start,
                image=analysis_image,
                synthesized=synthesized,
            )
        )
    return tuple(targets)
