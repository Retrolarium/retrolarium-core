// Cross-language parity for the Nemesis decoder.
//
// retrolarium_core owns the implementation Retrolarium and its Kit both use;
// python/retrolarium_core/oracles/nemesis.py is kept as the independent reference the
// port is checked against. The corpus comes from
// tools/generate-nemesis-golden.py.

#include <retrolarium/core/nemesis.hpp>

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

} // namespace

int main(int argc, char *argv[])
{
    if (argc != 2) {
        std::cerr << "usage: retrolarium-core-nemesis-golden-tests <corpus.txt>\n";
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
    std::vector<std::uint8_t> reference;
    std::vector<std::uint8_t> compressed;
    std::vector<std::uint8_t> expected;
    bool haveStream = false;
    int cases = 0;
    std::string line;
    bool firstLine = true;

    while (std::getline(stream, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        // An editor re-saving the corpus can prepend a UTF-8 BOM; skipping it
        // beats failing with a confusing "unknown key" on the first line.
        if (firstLine && line.rfind(kBom, 0) == 0) line.erase(0, kBom.size());
        firstLine = false;
        if (line.empty()) continue;
        std::istringstream fields(line);
        std::string key;
        fields >> key;

        if (key == "schema") {
            std::string value;
            fields >> value;
            if (value != "retrolarium.nemesis-golden") {
                std::cerr << "FAIL: unexpected corpus schema " << value << '\n';
                ++failures;
            }
        } else if (key == "schema_version" || key == "generator") {
            continue;
        } else if (key == "case" || key == "encode-case") {
            fields >> name;
            encoding = key == "encode-case";
            plain.clear();
            reference.clear();
            compressed.clear();
            expected.clear();
            haveStream = false;
        } else if (key == "plain") {
            std::string value;
            fields >> value;
            plain = fromHex(value);
            haveStream = true;
        } else if (key == "reference") {
            std::string value;
            fields >> value;
            reference = fromHex(value);
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
                const auto actual = encoding
                    ? retrolarium::core::nemesisCompress(plain, reference)
                    : retrolarium::core::nemesisDecompress(compressed);
                if (actual != expected) {
                    std::cerr << "FAIL: " << name << "\n  got    " << toHex(actual)
                              << "\n  wanted " << toHex(expected) << '\n';
                    ++failures;
                }
                if (encoding
                    && retrolarium::core::nemesisDecompress(actual) != plain) {
                    // A re-encoded stream must decode back to what it was given,
                    // or agreeing with the oracle would prove nothing.
                    std::cerr << "FAIL: " << name << " does not round-trip\n";
                    ++failures;
                }
            } catch (const retrolarium::core::NemesisError &error) {
                std::cerr << "FAIL: " << name << " rejected: " << error.what() << '\n';
                ++failures;
            }
        } else {
            std::cerr << "FAIL: unknown corpus key \"" << key << "\"\n";
            ++failures;
        }
    }

    if (cases == 0) {
        std::cerr << "corpus carried no cases\n";
        return 2;
    }
    if (failures != 0) {
        std::cerr << failures << " Nemesis parity check(s) failed\n";
        return 1;
    }
    std::cout << "Nemesis parity: " << cases << " cases\n";
    return 0;
}
