#pragma once

#include <cstdint>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace retrolarium::core {

// Raised when text does not fit its field or its glyph table.
class NesTextError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// A game's glyph table.
//
// `characters` is treated as a sequence of single-byte characters, which is
// what every NES font in the profiles uses. A multi-byte character would map
// per byte and diverge from the Python oracle, so the corpus generator refuses
// to emit a non-ASCII encoding rather than letting that happen unnoticed.
struct NesTextEncoding final {
    std::string characters;
    std::vector<int> codes;
    // "upper", "lower", or empty for no folding.
    std::string caseFold;
    int padding = 0;

    [[nodiscard]] std::map<char, int> encodeMap() const;
    [[nodiscard]] std::map<int, char> decodeMap() const;
};

// Encodes one fixed-width field, padding the remainder.
[[nodiscard]] std::vector<std::uint8_t> encodeText(const std::string &text,
    std::size_t width, const NesTextEncoding &encoding, const std::string &name);

// Decodes one fixed-width field.
//
// Trailing padding characters are stripped, so text that legitimately ends in
// the padding glyph cannot be represented. That is the oracle's behaviour and
// is reproduced rather than corrected.
[[nodiscard]] std::string decodeText(const std::vector<std::uint8_t> &payload,
    const NesTextEncoding &encoding, const std::string &name);

} // namespace retrolarium::core
