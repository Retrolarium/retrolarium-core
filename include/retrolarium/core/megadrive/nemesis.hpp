#pragma once

#include <cstdint>
#include <stdexcept>
#include <vector>

namespace retrolarium::core {

// Raised when a Nemesis stream ends early or is otherwise unreadable.
class NemesisError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// Decodes a Nemesis-compressed tile stream.
//
// The stream carries its own Huffman-style code table, so decoding needs
// nothing but the bytes. The 16-bit header holds the tile count in its low 15
// bits and selects XOR mode with the top bit; each tile expands to 32 bytes.
[[nodiscard]] std::vector<std::uint8_t> nemesisDecompress(
    const std::vector<std::uint8_t> &data);

} // namespace retrolarium::core
