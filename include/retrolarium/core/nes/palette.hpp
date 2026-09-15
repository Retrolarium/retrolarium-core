#pragma once

#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <utility>
#include <vector>

namespace retrolarium::core {

// Raised when palette data does not fit the NES colour range or its layout.
class NesPaletteError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// The NES has 64 colours, so every entry is a six-bit value.
constexpr int kNesColourMaximum = 0x3F;

// Decodes a contiguous palette table.
[[nodiscard]] std::vector<int> decodePaletteTable(
    const std::vector<std::uint8_t> &payload);

// Decodes a palette whose entries are stored in several places at once.
//
// Some games embed the same colour in more than one PPU command, so one
// logical entry has several physical copies. All copies must agree: if they do
// not, the profile's offsets describe something that is not a single palette,
// and silently taking the first would corrupt the others on the way back out.
[[nodiscard]] std::vector<int> decodeReplicatedPalette(
    const std::vector<std::uint8_t> &image,
    const std::vector<std::vector<std::size_t>> &offsets);

// Encodes a palette table, which must fill the resource exactly.
[[nodiscard]] std::vector<std::uint8_t> encodePaletteTable(
    const std::vector<int> &values, std::size_t expectedEntries);

// Produces one single-byte write per physical copy, so every replica is
// rewritten rather than just the first.
[[nodiscard]] std::vector<std::pair<std::size_t, std::uint8_t>>
encodeReplicatedPalette(const std::vector<int> &values,
    const std::vector<std::vector<std::size_t>> &offsets);

} // namespace retrolarium::core
