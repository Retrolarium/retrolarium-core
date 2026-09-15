// Cross-language parity for NES 2bpp character data.
//
// retrolarium_kit.nes_resources still decodes and encodes CHR for the Kit's own
// build path, so while both implementations exist this holds them together.
// The corpus comes from retrolarium_core/tools/generate-nes-tiles-golden.py.

#include <retrolarium/core/nes_tiles.hpp>

#include <cstdint>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace {

// A UTF-8 BOM, written as bytes so the constant does not depend on the
// source file's own encoding.
const std::string kBom {char(0xEF), char(0xBB), char(0xBF)};

int failures = 0;

std::vector<std::uint8_t> fromHex(const std::string &text)
{
    const auto nibble = [](char character) -> int {
        if (character >= '0' && character <= '9') return character - '0';
        if (character >= 'a' && character <= 'f') return character - 'a' + 10;
        if (character >= 'A' && character <= 'F') return character - 'A' + 10;
        return -1;
    };
    std::vector<std::uint8_t> out;
    out.reserve(text.size() / 2);
    for (std::size_t index = 0; index + 1 < text.size(); index += 2) {
        const int high = nibble(text[index]);
        const int low = nibble(text[index + 1]);
        if (high < 0 || low < 0) return {};
        out.push_back(static_cast<std::uint8_t>(high * 16 + low));
    }
    return out;
}

std::string flatten(const std::vector<retrolarium::core::NesTile> &tiles)
{
    std::string out;
    for (const auto &tile : tiles) {
        for (const auto &row : tile) {
            for (const int pixel : row) {
                out.push_back(static_cast<char>('0' + pixel));
            }
        }
    }
    return out;
}

void runCase(const std::string &name, const std::vector<std::uint8_t> &payload,
    std::size_t expectedTiles, const std::string &expectedPixels)
{
    std::vector<retrolarium::core::NesTile> tiles;
    try {
        tiles = retrolarium::core::decodeChr2bpp(payload);
    } catch (const retrolarium::core::NesTileError &error) {
        std::cerr << "FAIL: " << name << " did not decode: " << error.what() << '\n';
        ++failures;
        return;
    }

    if (tiles.size() != expectedTiles) {
        std::cerr << "FAIL: " << name << " tile count: got " << tiles.size()
                  << ", wanted " << expectedTiles << '\n';
        ++failures;
        return;
    }

    const std::string pixels = flatten(tiles);
    if (pixels != expectedPixels) {
        std::cerr << "FAIL: " << name << " pixels differ from the oracle\n";
        ++failures;
        return;
    }

    try {
        const auto reencoded = retrolarium::core::encodeChr2bpp(tiles, expectedTiles);
        if (reencoded != payload) {
            // A decoder that loses information would still match on pixels, so
            // the round trip is what proves it does not.
            std::cerr << "FAIL: " << name << " does not round-trip\n";
            ++failures;
        }
    } catch (const retrolarium::core::NesTileError &error) {
        std::cerr << "FAIL: " << name << " did not encode: " << error.what() << '\n';
        ++failures;
    }
}

void runMetatileCase(const std::string &name,
    const std::vector<std::uint8_t> &payload, std::size_t expectedRecords,
    const std::vector<int> &expectedValues)
{
    std::vector<retrolarium::core::NesMetatileRecord> records;
    try {
        records = retrolarium::core::decodeMetatileRecords(payload, expectedRecords);
    } catch (const retrolarium::core::NesTileError &error) {
        std::cerr << "FAIL: " << name << " did not decode: " << error.what() << '\n';
        ++failures;
        return;
    }

    std::vector<int> flat;
    for (const auto &record : records) {
        flat.insert(flat.end(), record.begin(), record.end());
    }
    if (flat != expectedValues) {
        std::cerr << "FAIL: " << name << " records differ from the oracle\n";
        ++failures;
        return;
    }

    try {
        if (retrolarium::core::encodeMetatileRecords(records, expectedRecords)
            != payload) {
            std::cerr << "FAIL: " << name << " does not round-trip\n";
            ++failures;
        }
    } catch (const retrolarium::core::NesTileError &error) {
        std::cerr << "FAIL: " << name << " did not encode: " << error.what() << '\n';
        ++failures;
    }
}

void checkRejections()
{
    // A payload that is not a whole number of tiles.
    try {
        static_cast<void>(retrolarium::core::decodeChr2bpp(
            std::vector<std::uint8_t>(17, 0)));
        std::cerr << "FAIL: a 17-byte payload was accepted\n";
        ++failures;
    } catch (const retrolarium::core::NesTileError &) {
    }

    // A tile count that does not fill the resource exactly.
    try {
        const retrolarium::core::NesTile tile(8, std::vector<int>(8, 0));
        static_cast<void>(retrolarium::core::encodeChr2bpp({tile}, 2));
        std::cerr << "FAIL: encoding one tile into a two-tile resource was accepted\n";
        ++failures;
    } catch (const retrolarium::core::NesTileError &) {
    }

    // A pixel outside the two bits the hardware has.
    try {
        retrolarium::core::NesTile tile(8, std::vector<int>(8, 0));
        tile[0][0] = 4;
        static_cast<void>(retrolarium::core::encodeChr2bpp({tile}, 1));
        std::cerr << "FAIL: a pixel value of 4 was accepted\n";
        ++failures;
    } catch (const retrolarium::core::NesTileError &) {
    }

    // A metatile range that is not a whole number of records.
    try {
        static_cast<void>(retrolarium::core::decodeMetatileRecords(
            std::vector<std::uint8_t>(6, 0), 2));
        std::cerr << "FAIL: a six-byte metatile range for two records was accepted\n";
        ++failures;
    } catch (const retrolarium::core::NesTileError &) {
    }

    // A record that is not four tile indexes.
    try {
        static_cast<void>(retrolarium::core::encodeMetatileRecords(
            {retrolarium::core::NesMetatileRecord {1, 2, 3}}, 1));
        std::cerr << "FAIL: a three-entry metatile record was accepted\n";
        ++failures;
    } catch (const retrolarium::core::NesTileError &) {
    }

    // A tile that is not eight rows.
    try {
        const retrolarium::core::NesTile tile(7, std::vector<int>(8, 0));
        static_cast<void>(retrolarium::core::encodeChr2bpp({tile}, 1));
        std::cerr << "FAIL: a seven-row tile was accepted\n";
        ++failures;
    } catch (const retrolarium::core::NesTileError &) {
    }
}

} // namespace

int main(int argc, char *argv[])
{
    if (argc != 2) {
        std::cerr << "usage: retrolarium-core-nes-tiles-golden-tests <corpus.txt>\n";
        return 2;
    }

    std::ifstream stream(argv[1]);
    if (!stream) {
        std::cerr << "cannot open corpus " << argv[1] << '\n';
        return 2;
    }

    std::string name;
    std::vector<std::uint8_t> payload;
    std::size_t expectedTiles = 0;
    std::string expectedPixels;
    bool metatile = false;
    std::size_t expectedRecords = 0;
    std::vector<int> expectedValues;
    int cases = 0;
    std::string line;
    bool firstLine = true;

    while (std::getline(stream, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (firstLine && line.rfind(kBom, 0) == 0) line.erase(0, kBom.size());
        firstLine = false;
        if (line.empty()) continue;
        std::istringstream fields(line);
        std::string key;
        fields >> key;

        if (key == "schema") {
            std::string value;
            fields >> value;
            if (value != "retrolarium.nes-tiles-golden") {
                std::cerr << "FAIL: unexpected corpus schema " << value << '\n';
                ++failures;
            }
        } else if (key == "schema_version" || key == "generator") {
            continue;
        } else if (key == "case" || key == "metatile-case") {
            fields >> name;
            metatile = key == "metatile-case";
            payload.clear();
            expectedTiles = 0;
            expectedRecords = 0;
            expectedPixels.clear();
            expectedValues.clear();
        } else if (key == "records") {
            fields >> expectedRecords;
        } else if (key == "values") {
            expectedValues.clear();
            int value = 0;
            while (fields >> value) {
                expectedValues.push_back(value);
            }
        } else if (key == "payload") {
            std::string value;
            fields >> value;
            payload = fromHex(value);
        } else if (key == "tiles") {
            fields >> expectedTiles;
        } else if (key == "pixels") {
            // An empty case carries no digits, so an absent value is valid.
            expectedPixels.clear();
            fields >> expectedPixels;
        } else if (key == "end") {
            ++cases;
            if (metatile) {
                runMetatileCase(name, payload, expectedRecords, expectedValues);
            } else {
                runCase(name, payload, expectedTiles, expectedPixels);
            }
        } else {
            std::cerr << "FAIL: unknown corpus key \"" << key << "\"\n";
            ++failures;
        }
    }

    checkRejections();

    if (cases == 0) {
        std::cerr << "corpus carried no cases\n";
        return 2;
    }
    if (failures != 0) {
        std::cerr << failures << " NES tile parity check(s) failed\n";
        return 1;
    }
    std::cout << "NES tile parity: " << cases << " cases\n";
    return 0;
}
