#pragma once

#include <cstdint>
#include <stdexcept>
#include <vector>

namespace retrolarium::core {

// Raised when tile data does not match the shape the NES hardware expects.
class NesTileError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// One 8x8 tile, row-major, each pixel 0..3.
using NesTile = std::vector<std::vector<int>>;

// Decodes NES 2bpp character data. Each tile is sixteen bytes: eight rows of
// the low bitplane followed by eight of the high one, so a pixel's two bits sit
// eight bytes apart rather than side by side.
[[nodiscard]] std::vector<NesTile> decodeChr2bpp(
    const std::vector<std::uint8_t> &payload);

// Encodes tiles back into 2bpp character data. `expectedTiles` is the capacity
// the resource must fill exactly - the ROM has no room for more and a short
// write would leave stale bytes behind.
[[nodiscard]] std::vector<std::uint8_t> encodeChr2bpp(
    const std::vector<NesTile> &tiles, std::size_t expectedTiles);

// One 2x2 metatile: four tile indices in the order the ROM stores them.
using NesMetatileRecord = std::vector<int>;

// Decodes fixed four-byte 2x2 metatile records.
//
// Only the record slicing lives here. Which group a record belongs to, and how
// a game encodes a metatile identifier into a group and a slot, is game
// semantics and stays out of the core.
[[nodiscard]] std::vector<NesMetatileRecord> decodeMetatileRecords(
    const std::vector<std::uint8_t> &payload, std::size_t expectedRecords);

[[nodiscard]] std::vector<std::uint8_t> encodeMetatileRecords(
    const std::vector<NesMetatileRecord> &records, std::size_t expectedRecords);

} // namespace retrolarium::core
