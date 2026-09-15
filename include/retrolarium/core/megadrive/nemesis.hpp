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

// Re-encodes tile data using the code table carried by `reference`.
//
// Nemesis has no standalone compressor: the code table is part of the stream,
// so re-encoding reuses the reference's header and table rather than inventing
// one. That removes the only genuinely lossy decision in the format and leaves
// run splitting as the single thing to reproduce. Callers that want the
// original bytes back for unchanged content compare the decoded content first
// and reuse `reference` verbatim; this function always re-encodes.
[[nodiscard]] std::vector<std::uint8_t> nemesisCompress(
    const std::vector<std::uint8_t> &plain,
    const std::vector<std::uint8_t> &reference);

} // namespace retrolarium::core
