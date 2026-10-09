#include <retrolarium/core/nes/nametable.hpp>

#include <string>

namespace retrolarium::core {
namespace {

void requireByte(int value, const std::string &where)
{
    if (value < 0 || value > 0xFF) {
        throw NesNametableError(where + " must be a byte in 0..255");
    }
}

} // namespace

NesNametable decodeNametable(
    const std::vector<std::uint8_t> &payload, std::size_t width, std::size_t height)
{
    const std::size_t cells = width * height;
    if (payload.size() < cells) {
        throw NesNametableError("nametable payload is shorter than its tile grid");
    }

    NesNametable result;
    result.tiles.reserve(height);
    for (std::size_t row = 0; row < height; ++row) {
        std::vector<int> line;
        line.reserve(width);
        for (std::size_t column = 0; column < width; ++column) {
            line.push_back(payload[row * width + column]);
        }
        result.tiles.push_back(std::move(line));
    }
    result.attributes.reserve(payload.size() - cells);
    for (std::size_t index = cells; index < payload.size(); ++index) {
        result.attributes.push_back(payload[index]);
    }
    return result;
}

std::vector<std::uint8_t> encodeNametable(const NesNametable &nametable,
    std::size_t width, std::size_t height, std::size_t attributeCount)
{
    if (nametable.tiles.size() != height) {
        throw NesNametableError(
            "tiles must contain " + std::to_string(height) + " rows");
    }
    if (nametable.attributes.size() != attributeCount) {
        throw NesNametableError("attributes must contain "
            + std::to_string(attributeCount) + " bytes");
    }

    std::vector<std::uint8_t> payload;
    payload.reserve(width * height + attributeCount);
    for (std::size_t row = 0; row < height; ++row) {
        const std::vector<int> &line = nametable.tiles[row];
        if (line.size() != width) {
            throw NesNametableError("tiles[" + std::to_string(row) + "] must contain "
                + std::to_string(width) + " entries");
        }
        for (std::size_t column = 0; column < width; ++column) {
            const std::string where = "tiles[" + std::to_string(row) + "]["
                + std::to_string(column) + "]";
            requireByte(line[column], where);
            payload.push_back(static_cast<std::uint8_t>(line[column]));
        }
    }
    for (std::size_t index = 0; index < attributeCount; ++index) {
        requireByte(nametable.attributes[index],
            "attributes[" + std::to_string(index) + "]");
        payload.push_back(static_cast<std::uint8_t>(nametable.attributes[index]));
    }
    return payload;
}

} // namespace retrolarium::core
