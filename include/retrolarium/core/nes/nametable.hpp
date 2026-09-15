#pragma once

#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace retrolarium::core {

// Raised when nametable data does not match its declared geometry.
class NesNametableError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

struct NesNametable final {
    // Row-major tile indices, `height` rows of `width` entries.
    std::vector<std::vector<int>> tiles;
    // The attribute bytes that follow the tile grid.
    std::vector<int> attributes;
};

// Splits a nametable payload into its tile grid and the attribute bytes that
// follow it. The attribute count is whatever the payload has left over, so the
// caller's geometry decides where the split falls.
[[nodiscard]] NesNametable decodeNametable(
    const std::vector<std::uint8_t> &payload, std::size_t width, std::size_t height);

// Rebuilds the payload. `attributeCount` is the capacity the resource must
// fill exactly, for the same reason tile counts are fixed: a short write would
// leave stale bytes in the ROM.
[[nodiscard]] std::vector<std::uint8_t> encodeNametable(const NesNametable &nametable,
    std::size_t width, std::size_t height, std::size_t attributeCount);

} // namespace retrolarium::core
