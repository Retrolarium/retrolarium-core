// libFuzzer target: any bytes through the Nemesis decoder, and a stream that
// decodes back through the encoder with itself as the reference. A refusal
// (NemesisError) is an answer; a crash, a sanitizer report or a re-encoding
// that decodes to something else is a bug.
//
// Built with -DRETROLARIUM_FUZZ=ON (Clang); seeds: fuzz/seed_corpus.py.

#include <retrolarium/core/megadrive/nemesis.hpp>

#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <vector>

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, std::size_t size) {
    const std::vector<std::uint8_t> stream(data, data + size);
    std::vector<std::uint8_t> plain;
    try {
        plain = retrolarium::core::nemesisDecompress(stream);
    } catch (const retrolarium::core::NemesisError&) {
        return 0;
    }
    // The encoder needs exactly the reference's tile count; a stream that
    // ends early decodes to fewer tiles.
    if (size < 2 || plain.size() != static_cast<std::size_t>(((stream[0] << 8) | stream[1]) & 0x7FFF) * 32) {
        return 0;
    }
    try {
        const auto repacked = retrolarium::core::nemesisCompress(plain, stream);
        if (retrolarium::core::nemesisDecompress(repacked) != plain) {
            std::abort();
        }
    } catch (const retrolarium::core::NemesisError&) {
    }
    return 0;
}
