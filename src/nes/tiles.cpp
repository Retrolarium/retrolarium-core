#include <retrolarium/core/nes/tiles.hpp>

#include <string>

namespace retrolarium::core {
namespace {

constexpr std::size_t kTileBytes = 16;
constexpr int kTileSide = 8;

} // namespace

std::vector<NesTile> decodeChr2bpp(const std::vector<std::uint8_t> &payload)
{
    if (payload.size() % kTileBytes != 0) {
        throw NesTileError("CHR 2bpp payload size must be divisible by 16");
    }

    std::vector<NesTile> tiles;
    tiles.reserve(payload.size() / kTileBytes);
    for (std::size_t start = 0; start < payload.size(); start += kTileBytes) {
        NesTile tile(kTileSide, std::vector<int>(kTileSide, 0));
        for (int y = 0; y < kTileSide; ++y) {
            const int low = payload[start + static_cast<std::size_t>(y)];
            const int high = payload[start + static_cast<std::size_t>(y) + 8];
            for (int x = 0; x < kTileSide; ++x) {
                const int shift = 7 - x;
                tile[static_cast<std::size_t>(y)][static_cast<std::size_t>(x)] =
                    ((low >> shift) & 1) | (((high >> shift) & 1) << 1);
            }
        }
        tiles.push_back(std::move(tile));
    }
    return tiles;
}

std::vector<std::uint8_t> encodeChr2bpp(
    const std::vector<NesTile> &tiles, std::size_t expectedTiles)
{
    if (tiles.size() != expectedTiles) {
        throw NesTileError(
            "CHR resource must contain " + std::to_string(expectedTiles) + " tiles");
    }

    std::vector<std::uint8_t> output;
    output.reserve(tiles.size() * kTileBytes);
    for (std::size_t index = 0; index < tiles.size(); ++index) {
        const NesTile &tile = tiles[index];
        const std::string where = "tiles[" + std::to_string(index) + "]";
        if (tile.size() != static_cast<std::size_t>(kTileSide)) {
            throw NesTileError(where + " must contain 8 rows");
        }

        std::uint8_t low[kTileSide] {};
        std::uint8_t high[kTileSide] {};
        for (int y = 0; y < kTileSide; ++y) {
            const std::vector<int> &row = tile[static_cast<std::size_t>(y)];
            if (row.size() != static_cast<std::size_t>(kTileSide)) {
                throw NesTileError(where + " must contain 8 columns per row");
            }
            for (int x = 0; x < kTileSide; ++x) {
                const int pixel = row[static_cast<std::size_t>(x)];
                if (pixel < 0 || pixel > 3) {
                    throw NesTileError(where + " pixels must be in 0..3");
                }
                const int shift = 7 - x;
                low[y] |= static_cast<std::uint8_t>((pixel & 1) << shift);
                high[y] |= static_cast<std::uint8_t>(((pixel >> 1) & 1) << shift);
            }
        }
        output.insert(output.end(), std::begin(low), std::end(low));
        output.insert(output.end(), std::begin(high), std::end(high));
    }
    return output;
}

std::vector<NesMetatileRecord> decodeMetatileRecords(
    const std::vector<std::uint8_t> &payload, std::size_t expectedRecords)
{
    const std::size_t expected = expectedRecords * 4;
    if (payload.size() != expected) {
        throw NesTileError("metatile range has " + std::to_string(payload.size())
            + " bytes, expected " + std::to_string(expected));
    }
    std::vector<NesMetatileRecord> records;
    records.reserve(expectedRecords);
    for (std::size_t offset = 0; offset < expected; offset += 4) {
        records.push_back({payload[offset], payload[offset + 1],
            payload[offset + 2], payload[offset + 3]});
    }
    return records;
}

std::vector<std::uint8_t> encodeMetatileRecords(
    const std::vector<NesMetatileRecord> &records, std::size_t expectedRecords)
{
    if (records.size() != expectedRecords) {
        throw NesTileError("records must contain " + std::to_string(expectedRecords)
            + " metatiles");
    }
    std::vector<std::uint8_t> output;
    output.reserve(records.size() * 4);
    for (std::size_t index = 0; index < records.size(); ++index) {
        const NesMetatileRecord &record = records[index];
        const std::string where = "records[" + std::to_string(index) + "]";
        if (record.size() != 4) {
            throw NesTileError(where + " must contain four tile indexes");
        }
        for (std::size_t slot = 0; slot < 4; ++slot) {
            const int value = record[slot];
            if (value < 0 || value > 0xFF) {
                throw NesTileError(where + "[" + std::to_string(slot)
                    + "] must be a byte in 0..255");
            }
            output.push_back(static_cast<std::uint8_t>(value));
        }
    }
    return output;
}

} // namespace retrolarium::core
