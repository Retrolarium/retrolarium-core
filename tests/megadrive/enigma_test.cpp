// The Enigma codec against its frozen corpus.
//
// retrolarium_core holds the only implementation, which the kit runs as
// rlcore. The historical Python corpus remains the byte-for-byte reference,
// except two header-repeat expectations were corrected against the 68000
// dispatch. Hand-packed regressions below cover all six-bit run lengths.

#include <retrolarium/core/megadrive/enigma.hpp>

#include <cstdint>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace {

// A UTF-8 BOM, written as bytes so the constant does not depend on the
// source file's own encoding.
const std::string kBom{char(0xEF), char(0xBB), char(0xBF)};

int failures = 0;

std::vector<std::uint8_t> fromHex(const std::string& text) {
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

std::string toHex(const std::vector<std::uint8_t>& data) {
    static constexpr char kDigits[] = "0123456789abcdef";
    std::string out;
    out.reserve(data.size() * 2);
    for (const std::uint8_t byte : data) {
        out.push_back(kDigits[byte >> 4]);
        out.push_back(kDigits[byte & 0xF]);
    }
    return out;
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc != 2) {
        std::cerr << "usage: retrolarium-core-enigma-golden-tests <corpus.txt>\n";
        return 2;
    }

    std::ifstream stream(argv[1]);
    if (!stream) {
        std::cerr << "cannot open corpus " << argv[1] << '\n';
        return 2;
    }

    std::string name;
    bool encoding = false;
    std::vector<std::uint8_t> plain;
    std::vector<std::uint8_t> compressed;
    std::vector<std::uint8_t> expected;
    int baseTile = 0;
    bool haveStream = false;
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
            if (value != "retrolarium.enigma-golden") {
                std::cerr << "FAIL: unexpected corpus schema " << value << '\n';
                ++failures;
            }
        } else if (key == "schema_version" || key == "generator" || key == "unreachable_modes") {
            continue;
        } else if (key == "case" || key == "encode-case") {
            fields >> name;
            encoding = key == "encode-case";
            plain.clear();
            compressed.clear();
            expected.clear();
            baseTile = 0;
            haveStream = false;
        } else if (key == "plain") {
            std::string value;
            fields >> value;
            plain = fromHex(value);
            haveStream = true;
        } else if (key == "base_tile") {
            fields >> baseTile;
        } else if (key == "stream") {
            std::string value;
            fields >> value;
            compressed = fromHex(value);
            haveStream = true;
        } else if (key == "expect") {
            std::string value;
            fields >> value;
            expected = fromHex(value);
        } else if (key == "end") {
            if (!haveStream) {
                std::cerr << "FAIL: " << name << " has no stream\n";
                ++failures;
                continue;
            }
            ++cases;
            try {
                const auto actual = encoding ? retrolarium::core::enigmaCompress(plain)
                                             : retrolarium::core::enigmaDecompress(compressed, baseTile);
                if (actual != expected) {
                    std::cerr << "FAIL: " << name << "\n  got    " << toHex(actual) << "\n  wanted " << toHex(expected)
                              << '\n';
                    ++failures;
                }
                if (encoding && retrolarium::core::enigmaDecompress(actual, 0) != plain) {
                    // A stream the encoder emits must decode back to its input,
                    // or agreeing with the oracle would prove nothing.
                    std::cerr << "FAIL: " << name << " does not round-trip\n";
                    ++failures;
                }
            } catch (const retrolarium::core::EnigmaError& error) {
                std::cerr << "FAIL: " << name << " rejected: " << error.what() << '\n';
                ++failures;
            }
        } else {
            std::cerr << "FAIL: unknown corpus key \"" << key << "\"\n";
            ++failures;
        }
    }

    // The six-bit commands are 00rrrr (incrementing header tile) and
    // 01rrrr (static header tile). Flicky's ASM shifts d2 for the repeat
    // count but retains d1 for dispatch: slots 0/1 increment, 2/3 repeat.
    // These hand-packed streams are independent of the retired Python oracle.
    for (const bool fixed : {false, true}) {
        for (int count = 1; count <= 16; ++count) {
            for (const int base : {0, 0x300}) {
                const int command = (fixed ? 0x10 : 0) | (count - 1);
                const int bits = (command << 10) | (0x7F << 3);
                const std::vector<std::uint8_t> data{1,
                                                     0,
                                                     0,
                                                     0x10,
                                                     0,
                                                     0x20,
                                                     static_cast<std::uint8_t>(bits >> 8),
                                                     static_cast<std::uint8_t>(bits & 0xFF)};
                std::vector<std::uint8_t> wanted;
                for (int index = 0; index < count; ++index) {
                    const int tile = base + (fixed ? 0x20 : 0x10 + index);
                    wanted.push_back(static_cast<std::uint8_t>(tile >> 8));
                    wanted.push_back(static_cast<std::uint8_t>(tile & 0xFF));
                }
                if (retrolarium::core::enigmaDecompress(data, base) != wanted) {
                    std::cerr << "FAIL: six-bit " << (fixed ? "static" : "incrementing") << " run of " << count
                              << " at base " << base << "\n";
                    ++failures;
                }
            }
        }
    }

    // Broken streams are refused: never decoded outside the code table,
    // for ever, or past the plane they could fill.
    for (const char* broken : {"0000000000000000", "2000000000008000000001fc0000"}) {
        try {
            (void)retrolarium::core::enigmaDecompress(fromHex(broken));
            std::cerr << "FAIL: the broken stream " << broken << " decoded\n";
            ++failures;
        } catch (const retrolarium::core::EnigmaError&) {
        }
    }

    // Exactly the decoder limit round-trips; one word beyond is refused
    // before allocating the encoder's search graph.
    const std::vector<std::uint8_t> maximum(0x10000, 0);
    if (retrolarium::core::enigmaDecompress(retrolarium::core::enigmaCompress(maximum)) != maximum) {
        std::cerr << "FAIL: the maximum supported Enigma map does not round-trip\n";
        ++failures;
    }
    try {
        (void)retrolarium::core::enigmaCompress(std::vector<std::uint8_t>(0x10002, 0));
        std::cerr << "FAIL: Enigma accepted more than the decoder limit\n";
        ++failures;
    } catch (const retrolarium::core::EnigmaError&) {
    }

    if (cases == 0) {
        std::cerr << "corpus carried no cases\n";
        return 2;
    }
    if (failures != 0) {
        std::cerr << failures << " Enigma parity check(s) failed\n";
        return 1;
    }
    std::cout << "Enigma parity: " << cases << " cases\n";
    return 0;
}
