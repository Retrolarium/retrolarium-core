// Cross-language parity for the NES palette and nametable kernels.
//
// Neither format has a standalone function in the Kit - the logic sits inside
// decode_resources and build_resources - so the corpus is produced by driving
// those through a real profile, in
// retrolarium_core/tools/generate-nes-surfaces-golden.py.

#include <retrolarium/core/nes_nametable.hpp>
#include <retrolarium/core/nes_palette.hpp>

#include <algorithm>
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

void report(const std::string &message)
{
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
}

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

std::string toHex(const std::vector<std::uint8_t> &data)
{
    static constexpr char kDigits[] = "0123456789abcdef";
    std::string out;
    out.reserve(data.size() * 2);
    for (const std::uint8_t byte : data) {
        out.push_back(kDigits[byte >> 4]);
        out.push_back(kDigits[byte & 0xF]);
    }
    return out;
}

std::vector<int> parseIntList(const std::string &text)
{
    std::vector<int> values;
    std::istringstream stream(text);
    int value = 0;
    while (stream >> value) {
        values.push_back(value);
    }
    return values;
}

// "1,8,15;29,36,43" -> {{1,8,15},{29,36,43}}
std::vector<std::vector<int>> parseGroups(const std::string &text)
{
    std::vector<std::vector<int>> groups;
    std::istringstream outer(text);
    std::string group;
    while (std::getline(outer, group, ';')) {
        std::vector<int> row;
        std::istringstream inner(group);
        std::string item;
        while (std::getline(inner, item, ',')) {
            if (!item.empty()) {
                row.push_back(std::stoi(item));
            }
        }
        groups.push_back(std::move(row));
    }
    return groups;
}

std::string describe(const std::vector<int> &values)
{
    std::string out;
    for (std::size_t index = 0; index < values.size(); ++index) {
        if (index != 0) out += ' ';
        out += std::to_string(values[index]);
    }
    return out;
}

struct Section final {
    std::string kind;
    std::string name;
    std::string payload;
    std::string offsets;
    std::string values;
    std::string editedValues;
    std::string editedPayload;
    std::string editedBytes;
    std::string tiles;
    std::string attributes;
    std::string editedTiles;
    std::string editedAttributes;
    int width = 0;
    int height = 0;
    int attributeCount = 0;
};

void runContiguousPalette(const Section &section)
{
    const auto payload = fromHex(section.payload);
    const auto wanted = parseIntList(section.values);
    const auto values = retrolarium::core::decodePaletteTable(payload);
    if (values != wanted) {
        report(section.name + " values: got [" + describe(values) + "], wanted ["
            + describe(wanted) + "]");
    }

    const auto edited = parseIntList(section.editedValues);
    const auto rebuilt = retrolarium::core::encodePaletteTable(edited, edited.size());
    if (toHex(rebuilt) != section.editedPayload) {
        report(section.name + " edited payload: got " + toHex(rebuilt) + ", wanted "
            + section.editedPayload);
    }
}

void runReplicatedPalette(const Section &section)
{
    const auto groups = parseGroups(section.offsets);
    const auto wanted = parseIntList(section.values);

    std::vector<std::vector<std::size_t>> offsets;
    std::size_t highest = 0;
    for (const auto &group : groups) {
        std::vector<std::size_t> converted;
        for (const int offset : group) {
            converted.push_back(static_cast<std::size_t>(offset));
            highest = std::max(highest, static_cast<std::size_t>(offset));
        }
        offsets.push_back(std::move(converted));
    }

    // Rebuild the image the offsets describe: every copy of an entry holds the
    // same value, which is exactly what the decoder has to insist on.
    std::vector<std::uint8_t> image(highest + 1, 0);
    for (std::size_t entry = 0; entry < offsets.size() && entry < wanted.size();
        ++entry) {
        for (const std::size_t offset : offsets[entry]) {
            image[offset] = static_cast<std::uint8_t>(wanted[entry]);
        }
    }

    const auto values = retrolarium::core::decodeReplicatedPalette(image, offsets);
    if (values != wanted) {
        report(section.name + " values: got [" + describe(values) + "], wanted ["
            + describe(wanted) + "]");
    }

    // Disagreeing replicas describe something that is not one palette, and
    // taking the first would corrupt the others on the way back out.
    if (offsets.front().size() > 1) {
        auto broken = image;
        broken[offsets.front()[1]] ^= 0x01;
        try {
            static_cast<void>(
                retrolarium::core::decodeReplicatedPalette(broken, offsets));
            report(section.name + " accepted replicas that disagree");
        } catch (const retrolarium::core::NesPaletteError &) {
        }
    }

    const auto edited = parseIntList(section.editedValues);
    const auto spans = retrolarium::core::encodeReplicatedPalette(edited, offsets);
    const auto wantedGroups = parseGroups(section.editedBytes);

    std::size_t span = 0;
    for (std::size_t entry = 0; entry < offsets.size(); ++entry) {
        for (std::size_t copy = 0; copy < offsets[entry].size(); ++copy) {
            if (span >= spans.size() || entry >= wantedGroups.size()
                || copy >= wantedGroups[entry].size()) {
                report(section.name + " produced too few writes");
                return;
            }
            if (spans[span].first != offsets[entry][copy]
                || spans[span].second != wantedGroups[entry][copy]) {
                report(section.name + " write " + std::to_string(span)
                    + " differs from the oracle");
            }
            ++span;
        }
    }
    if (span != spans.size()) {
        report(section.name + " produced more writes than the oracle");
    }
}

void runNametable(const Section &section)
{
    const auto payload = fromHex(section.payload);
    const auto width = static_cast<std::size_t>(section.width);
    const auto height = static_cast<std::size_t>(section.height);
    const auto attributeCount = static_cast<std::size_t>(section.attributeCount);

    const auto decoded = retrolarium::core::decodeNametable(payload, width, height);
    const auto wantedTiles = parseGroups(section.tiles);
    if (decoded.tiles != wantedTiles) {
        report(section.name + " tiles differ from the oracle");
    }
    const auto wantedAttributes = parseIntList(section.attributes);
    if (decoded.attributes != wantedAttributes) {
        report(section.name + " attributes: got [" + describe(decoded.attributes)
            + "], wanted [" + describe(wantedAttributes) + "]");
    }

    retrolarium::core::NesNametable edited;
    edited.tiles = parseGroups(section.editedTiles);
    edited.attributes = parseIntList(section.editedAttributes);
    const auto rebuilt =
        retrolarium::core::encodeNametable(edited, width, height, attributeCount);
    if (toHex(rebuilt) != section.editedPayload) {
        report(section.name + " edited payload: got " + toHex(rebuilt) + ", wanted "
            + section.editedPayload);
    }

    // A grid that is short by one row must be refused rather than padded.
    try {
        retrolarium::core::NesNametable shortened = edited;
        shortened.tiles.pop_back();
        static_cast<void>(retrolarium::core::encodeNametable(
            shortened, width, height, attributeCount));
        report(section.name + " accepted a grid with a missing row");
    } catch (const retrolarium::core::NesNametableError &) {
    }
}

std::string rest(std::istringstream &fields)
{
    std::string value;
    std::getline(fields, value);
    if (!value.empty() && value.front() == ' ') {
        value.erase(0, 1);
    }
    return value;
}

} // namespace

int main(int argc, char *argv[])
{
    if (argc != 2) {
        std::cerr << "usage: retrolarium-core-nes-surfaces-golden-tests <corpus.txt>\n";
        return 2;
    }

    std::ifstream stream(argv[1]);
    if (!stream) {
        std::cerr << "cannot open corpus " << argv[1] << '\n';
        return 2;
    }

    Section current;
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
            if (value != "retrolarium.nes-surfaces-golden") {
                report("unexpected corpus schema " + value);
            }
        } else if (key == "schema_version" || key == "generator") {
            continue;
        } else if (key == "palette-case" || key == "nametable-case") {
            current = Section {};
            current.kind = key;
            fields >> current.name;
        } else if (key == "payload") {
            fields >> current.payload;
        } else if (key == "offsets") {
            fields >> current.offsets;
        } else if (key == "values") {
            current.values = rest(fields);
        } else if (key == "edited-values") {
            current.editedValues = rest(fields);
        } else if (key == "edited-payload") {
            fields >> current.editedPayload;
        } else if (key == "edited-bytes") {
            fields >> current.editedBytes;
        } else if (key == "width") {
            fields >> current.width;
        } else if (key == "height") {
            fields >> current.height;
        } else if (key == "attribute-count") {
            fields >> current.attributeCount;
        } else if (key == "tiles") {
            fields >> current.tiles;
        } else if (key == "attributes") {
            current.attributes = rest(fields);
        } else if (key == "edited-tiles") {
            fields >> current.editedTiles;
        } else if (key == "edited-attributes") {
            current.editedAttributes = rest(fields);
        } else if (key == "end") {
            ++cases;
            try {
                if (current.kind == "nametable-case") {
                    runNametable(current);
                } else if (!current.offsets.empty()) {
                    runReplicatedPalette(current);
                } else {
                    runContiguousPalette(current);
                }
            } catch (const std::exception &error) {
                report(current.name + " raised: " + error.what());
            }
        } else {
            report("unknown corpus key \"" + key + "\"");
        }
    }

    if (cases == 0) {
        std::cerr << "corpus carried no cases\n";
        return 2;
    }
    if (failures != 0) {
        std::cerr << failures << " NES surface parity check(s) failed\n";
        return 1;
    }
    std::cout << "NES surface parity: " << cases << " cases\n";
    return 0;
}
