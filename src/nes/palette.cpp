#include <retrolarium/core/nes_palette.hpp>

#include <string>

namespace retrolarium::core {
namespace {

void requireColour(int value, const std::string &where)
{
    if (value < 0 || value > kNesColourMaximum) {
        throw NesPaletteError(where + " must be an NES colour in 0..63");
    }
}

} // namespace

std::vector<int> decodePaletteTable(const std::vector<std::uint8_t> &payload)
{
    std::vector<int> values;
    values.reserve(payload.size());
    for (std::size_t index = 0; index < payload.size(); ++index) {
        const int value = payload[index];
        requireColour(value, "values[" + std::to_string(index) + "]");
        values.push_back(value);
    }
    return values;
}

std::vector<int> decodeReplicatedPalette(const std::vector<std::uint8_t> &image,
    const std::vector<std::vector<std::size_t>> &offsets)
{
    std::vector<int> values;
    values.reserve(offsets.size());
    for (std::size_t entry = 0; entry < offsets.size(); ++entry) {
        const std::vector<std::size_t> &copies = offsets[entry];
        const std::string where = "values[" + std::to_string(entry) + "]";
        if (copies.empty()) {
            throw NesPaletteError(where + " has no stored copies");
        }
        int first = 0;
        for (std::size_t index = 0; index < copies.size(); ++index) {
            const std::size_t offset = copies[index];
            if (offset >= image.size()) {
                throw NesPaletteError(where + " exceeds the source image");
            }
            const int value = image[offset];
            if (index == 0) {
                first = value;
            } else if (value != first) {
                throw NesPaletteError(where + " replicas differ");
            }
        }
        requireColour(first, where);
        values.push_back(first);
    }
    return values;
}

std::vector<std::uint8_t> encodePaletteTable(
    const std::vector<int> &values, std::size_t expectedEntries)
{
    if (values.size() != expectedEntries) {
        throw NesPaletteError(
            "values must contain " + std::to_string(expectedEntries) + " bytes");
    }
    std::vector<std::uint8_t> payload;
    payload.reserve(values.size());
    for (std::size_t index = 0; index < values.size(); ++index) {
        requireColour(values[index], "values[" + std::to_string(index) + "]");
        payload.push_back(static_cast<std::uint8_t>(values[index]));
    }
    return payload;
}

std::vector<std::pair<std::size_t, std::uint8_t>> encodeReplicatedPalette(
    const std::vector<int> &values,
    const std::vector<std::vector<std::size_t>> &offsets)
{
    if (values.size() != offsets.size()) {
        throw NesPaletteError(
            "values must contain " + std::to_string(offsets.size()) + " bytes");
    }
    std::vector<std::pair<std::size_t, std::uint8_t>> spans;
    for (std::size_t entry = 0; entry < values.size(); ++entry) {
        const std::string where = "values[" + std::to_string(entry) + "]";
        requireColour(values[entry], where);
        if (offsets[entry].empty()) {
            throw NesPaletteError(where + " has no stored copies");
        }
        for (const std::size_t offset : offsets[entry]) {
            spans.emplace_back(offset, static_cast<std::uint8_t>(values[entry]));
        }
    }
    return spans;
}

} // namespace retrolarium::core
