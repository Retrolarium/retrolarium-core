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

// The Enigma variant implemented here is the one Flicky's 68000 decoder reads,
// checked against that routine; it is not the standard EniDec of the Sonic
// games. Both share the header layout, the command set (incrementing and
// static copies from the header's two tiles, inline repeat, increment,
// decrement and literal runs, with 0x7F ending the stream) and the bit packing.
// They differ in the flag mask, the header's second byte:
//
// - Flicky turns the mask with ror.l #1 then ror.w #1, so mask bit 0 enables
//   the V-flip bit (0x1000) of each inline tile and mask bit 1 the H-flip bit
//   (0x0800); the standard EniDec gives bit 0 to H-flip and bit 1 to V-flip.
// - Flicky ignores mask bits 2 to 4: inline tiles carry no priority or palette
//   bits, where the standard EniDec reads them (0x8000, 0x4000, 0x2000).
//
// A stream with a zero flag mask, which is what enigmaCompress writes, decodes
// the same under both. The golden corpus pins this behaviour.

// Decodes an Enigma-compressed tilemap (Flicky's variant, see above) into
// big-endian tile words.
//
// `baseTile` is added to every tile the stream produces, which is how the game
// reuses one map against different VRAM layouts.
[[nodiscard]] std::vector<std::uint8_t> enigmaDecompress(const std::vector<std::uint8_t>& data, int baseTile = 0);

// Encodes big-endian tile words back into an Enigma stream.
//
// This is an optimising encoder: it searches for the cheapest command sequence
// rather than emitting a straightforward one, so its output is byte-comparable
// with the Python oracle only because both make the same choices in the same
// order. Attribute flags are folded into the tile word, so the stream carries a
// zero flag byte and enough tile bits for the largest word.
[[nodiscard]] std::vector<std::uint8_t> enigmaCompress(const std::vector<std::uint8_t>& data);

}  // namespace retrolarium::core
