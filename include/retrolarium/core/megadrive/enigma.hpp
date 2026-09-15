#pragma once

#include <cstdint>
#include <stdexcept>
#include <vector>

namespace retrolarium::core {

// Raised when an Enigma stream ends before its terminator.
class EnigmaError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// Decodes an Enigma-compressed tilemap into big-endian tile words.
//
// `baseTile` is added to every tile the stream produces, which is how the game
// reuses one map against different VRAM layouts.
[[nodiscard]] std::vector<std::uint8_t> enigmaDecompress(
    const std::vector<std::uint8_t> &data, int baseTile = 0);

// Encodes big-endian tile words back into an Enigma stream.
//
// This is an optimising encoder: it searches for the cheapest command sequence
// rather than emitting a straightforward one, so its output is byte-comparable
// with the Python oracle only because both make the same choices in the same
// order. Attribute flags are folded into the tile word, so the stream carries a
// zero flag byte and enough tile bits for the largest word.
[[nodiscard]] std::vector<std::uint8_t> enigmaCompress(
    const std::vector<std::uint8_t> &data);

} // namespace retrolarium::core
