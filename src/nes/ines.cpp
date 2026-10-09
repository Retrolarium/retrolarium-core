#include <retrolarium/core/nes/ines.hpp>

#include <retrolarium/core/hash/sha256.hpp>

#include <fstream>
#include <utility>

namespace retrolarium::core {
namespace {

constexpr std::size_t kHeaderSize = 16;
constexpr std::size_t kTrainerSize = 512;
constexpr std::size_t kPrgUnit = 0x4000;
constexpr std::size_t kChrUnit = 0x2000;

ImageRegion makeRegion(
    const char *name, std::size_t offset, const std::vector<std::uint8_t> &payload)
{
    return ImageRegion {name, offset, payload.size(), sha256Hex(payload)};
}

std::vector<std::uint8_t> slice(
    const std::vector<std::uint8_t> &data, std::size_t offset, std::size_t size)
{
    return {data.begin() + static_cast<std::ptrdiff_t>(offset),
        data.begin() + static_cast<std::ptrdiff_t>(offset + size)};
}

} // namespace

std::string mirroringName(Mirroring mirroring)
{
    switch (mirroring) {
    case Mirroring::Vertical:
        return "vertical";
    case Mirroring::FourScreen:
        return "four-screen";
    case Mirroring::Horizontal:
        break;
    }
    return "horizontal";
}

std::vector<ImageRegion> InesImage::regions() const
{
    std::vector<ImageRegion> result;
    std::size_t offset = 0;
    result.push_back(makeRegion("header", offset, header));
    offset += header.size();
    if (!trainer.empty()) {
        result.push_back(makeRegion("trainer", offset, trainer));
        offset += trainer.size();
    }
    result.push_back(makeRegion("prg", offset, prg));
    offset += prg.size();
    if (!chr.empty()) {
        result.push_back(makeRegion("chr", offset, chr));
    }
    return result;
}

std::size_t declaredInesSize(const std::vector<std::uint8_t> &data)
{
    if (data.size() < kHeaderSize || data[0] != 'N' || data[1] != 'E'
        || data[2] != 'S' || data[3] != 0x1a) {
        throw InesError("missing iNES magic");
    }
    const std::uint8_t flags6 = data[6];
    const std::uint8_t flags7 = data[7];
    if ((flags7 & 0x0C) == 0x08) {
        throw InesError("NES 2.0 is not supported by the initial NROM pipeline");
    }
    if (data[4] == 0) {
        throw InesError("iNES image declares no PRG ROM");
    }

    const std::size_t trainerSize = (flags6 & 0x04) != 0 ? kTrainerSize : 0;
    return kHeaderSize + trainerSize + data[4] * kPrgUnit + data[5] * kChrUnit;
}

InesImage parseInes(std::vector<std::uint8_t> data)
{
    const std::size_t expected = declaredInesSize(data);
    if (data.size() != expected) {
        throw InesError("image size is " + std::to_string(data.size())
            + ", header describes " + std::to_string(expected) + " bytes");
    }

    const std::uint8_t flags6 = data[6];
    const std::uint8_t flags7 = data[7];
    const std::size_t trainerSize = (flags6 & 0x04) != 0 ? kTrainerSize : 0;
    const std::size_t prgSize = data[4] * kPrgUnit;
    const std::size_t chrSize = data[5] * kChrUnit;

    InesImage image;
    image.header = slice(data, 0, kHeaderSize);
    std::size_t cursor = kHeaderSize;
    image.trainer = slice(data, cursor, trainerSize);
    cursor += trainerSize;
    image.prg = slice(data, cursor, prgSize);
    cursor += prgSize;
    image.chr = slice(data, cursor, chrSize);

    image.mapper = (flags6 >> 4) | (flags7 & 0xF0);
    if ((flags6 & 0x08) != 0) {
        image.mirroring = Mirroring::FourScreen;
    } else if ((flags6 & 0x01) != 0) {
        image.mirroring = Mirroring::Vertical;
    } else {
        image.mirroring = Mirroring::Horizontal;
    }
    image.battery = (flags6 & 0x02) != 0;
    image.sha256 = sha256Hex(data);
    image.data = std::move(data);
    return image;
}

std::pair<InesImage, std::vector<std::uint8_t>> parseInesPrefix(
    const std::vector<std::uint8_t> &data)
{
    const std::size_t expected = declaredInesSize(data);
    if (data.size() < expected) {
        throw InesError("image size is " + std::to_string(data.size())
            + ", header describes " + std::to_string(expected) + " bytes");
    }
    return {parseInes(slice(data, 0, expected)),
        slice(data, expected, data.size() - expected)};
}

InesImage loadInes(const std::string &path)
{
    std::ifstream stream(path, std::ios::binary);
    if (!stream) {
        throw InesError("cannot open " + path);
    }
    std::vector<std::uint8_t> data(
        (std::istreambuf_iterator<char>(stream)), std::istreambuf_iterator<char>());
    return parseInes(std::move(data));
}

} // namespace retrolarium::core
