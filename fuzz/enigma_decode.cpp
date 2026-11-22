// libFuzzer target: any bytes through the Enigma decoder. A refusal
// (EnigmaError) is an answer; a crash or a sanitizer report is a bug. The
// first byte picks a base tile within the range rlcore accepts, so the base
// tile arithmetic is exercised too.
//
// Built with -DRETROLARIUM_FUZZ=ON (Clang); seeds: fuzz/seed_corpus.py.

#include <retrolarium/core/megadrive/enigma.hpp>

#include <cstddef>
#include <cstdint>
#include <vector>

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, std::size_t size) {
    if (size == 0) {
        return 0;
    }
    // 0 for most seeds (their first byte is a small bit count), up to 0xFF00.
    const int baseTile = (data[0] & 0x80) != 0 ? (data[0] & 0x7F) << 9 : 0;
    const std::vector<std::uint8_t> stream(data, data + size);
    try {
        (void)retrolarium::core::enigmaDecompress(stream, baseTile);
    } catch (const retrolarium::core::EnigmaError&) {
    }
    return 0;
}
