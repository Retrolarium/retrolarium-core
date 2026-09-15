#include <retrolarium/core/nes_text.hpp>

#include <algorithm>
#include <cctype>
#include <set>

namespace retrolarium::core {
namespace {

std::string fold(const std::string &text, const std::string &caseFold)
{
    if (caseFold != "upper" && caseFold != "lower") {
        return text;
    }
    std::string out = text;
    for (char &character : out) {
        const auto value = static_cast<unsigned char>(character);
        character = caseFold == "upper"
            ? static_cast<char>(std::toupper(value))
            : static_cast<char>(std::tolower(value));
    }
    return out;
}

std::string hexByte(int value)
{
    static constexpr char kDigits[] = "0123456789ABCDEF";
    std::string out = "$";
    out.push_back(kDigits[(value >> 4) & 0xF]);
    out.push_back(kDigits[value & 0xF]);
    return out;
}

} // namespace

std::map<char, int> NesTextEncoding::encodeMap() const
{
    std::map<char, int> map;
    const std::size_t count = std::min(characters.size(), codes.size());
    for (std::size_t index = 0; index < count; ++index) {
        map.emplace(characters[index], codes[index]);
    }
    return map;
}

std::map<int, char> NesTextEncoding::decodeMap() const
{
    std::map<int, char> map;
    const std::size_t count = std::min(characters.size(), codes.size());
    for (std::size_t index = 0; index < count; ++index) {
        map.emplace(codes[index], characters[index]);
    }
    return map;
}

std::vector<std::uint8_t> encodeText(const std::string &text, std::size_t width,
    const NesTextEncoding &encoding, const std::string &name)
{
    const std::string normalized = fold(text, encoding.caseFold);
    if (normalized.size() > width) {
        throw NesTextError(name + ".text exceeds its fixed width of "
            + std::to_string(width));
    }

    const auto map = encoding.encodeMap();
    std::set<char> unsupported;
    for (const char character : normalized) {
        if (map.find(character) == map.end()) {
            unsupported.insert(character);
        }
    }
    if (!unsupported.empty()) {
        std::string rendered;
        for (const char character : unsupported) {
            if (!rendered.empty()) rendered += ' ';
            rendered += '\'';
            rendered += character;
            rendered += '\'';
        }
        throw NesTextError(name + ".text contains unsupported characters: " + rendered);
    }

    std::vector<std::uint8_t> result;
    result.reserve(width);
    for (const char character : normalized) {
        result.push_back(static_cast<std::uint8_t>(map.at(character)));
    }
    result.resize(width, static_cast<std::uint8_t>(encoding.padding));
    return result;
}

std::string decodeText(const std::vector<std::uint8_t> &payload,
    const NesTextEncoding &encoding, const std::string &name)
{
    const auto map = encoding.decodeMap();
    std::string rendered;
    rendered.reserve(payload.size());
    for (const std::uint8_t value : payload) {
        const auto found = map.find(value);
        if (found == map.end()) {
            throw NesTextError(name + " contains unmapped glyph " + hexByte(value));
        }
        rendered.push_back(found->second);
    }

    const auto padding = map.find(encoding.padding);
    if (padding == map.end()) {
        throw NesTextError(name + " padding glyph is not in the encoding");
    }
    // Trailing padding is stripped, so text ending in the padding glyph cannot
    // round-trip. That is the oracle's behaviour, reproduced rather than fixed.
    while (!rendered.empty() && rendered.back() == padding->second) {
        rendered.pop_back();
    }
    return rendered;
}

} // namespace retrolarium::core
