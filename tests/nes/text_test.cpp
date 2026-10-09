// Cross-language parity for fixed-width text fields.
//
// The corpus comes from retrolarium-core/tools/generate-nes-text-golden.py,
// which drives retrolarium_kit.platform.nes.text.

#include <retrolarium/core/nes_text.hpp>

#include <cstdint>
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

namespace {

// A UTF-8 BOM, written as bytes so the constant does not depend on the
// source file's own encoding.
const std::string kBom {char(0xEF), char(0xBB), char(0xBF)};

int failures = 0;

void report(const std::string &message)
{
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
}

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

std::vector<int> parseCsv(const std::string &text)
{
    std::vector<int> values;
    std::istringstream stream(text);
    std::string item;
    while (std::getline(stream, item, ',')) {
        if (!item.empty()) values.push_back(std::stoi(item));
    }
    return values;
}

// Everything after the key, with exactly one separating space removed. Text
// fields can contain spaces and can be empty, so they cannot be read with >>.
std::string valueOf(const std::string &line, const std::string &key)
{
    if (line.size() <= key.size()) return {};
    return line.substr(key.size() + 1);
}

} // namespace

int main(int argc, char *argv[])
{
    if (argc != 2) {
        std::cerr << "usage: retrolarium-core-nes-text-golden-tests <corpus.txt>\n";
        return 2;
    }

    std::ifstream stream(argv[1]);
    if (!stream) {
        std::cerr << "cannot open corpus " << argv[1] << '\n';
        return 2;
    }

    std::map<std::string, retrolarium::core::NesTextEncoding> encodings;
    std::string encodingKey;
    retrolarium::core::NesTextEncoding building;

    enum class Mode { None, Encoding, Case, Reject, RejectDecode };
    Mode mode = Mode::None;

    std::string name;
    std::string caseEncodingKey;
    std::string text;
    std::string decoded;
    std::size_t width = 0;
    std::vector<std::uint8_t> payload;

    int cases = 0;
    int rejections = 0;
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
            if (value != "retrolarium.nes-text-golden") {
                report("unexpected corpus schema " + value);
            }
        } else if (key == "schema_version" || key == "generator") {
            continue;
        } else if (key == "encoding") {
            mode = Mode::Encoding;
            fields >> encodingKey;
            building = retrolarium::core::NesTextEncoding {};
        } else if (key == "characters") {
            building.characters = valueOf(line, key);
        } else if (key == "codes") {
            building.codes = parseCsv(valueOf(line, key));
        } else if (key == "case-fold") {
            std::string value;
            fields >> value;
            building.caseFold = value == "-" ? std::string {} : value;
        } else if (key == "padding") {
            fields >> building.padding;
        } else if (key == "case" || key == "reject-case") {
            mode = key == "case" ? Mode::Case : Mode::Reject;
            fields >> name;
            text.clear();
            decoded.clear();
            payload.clear();
            width = 0;
        } else if (key == "reject-decode") {
            mode = Mode::RejectDecode;
            fields >> name;
            payload.clear();
        } else if (key == "encoding-key") {
            fields >> caseEncodingKey;
        } else if (key == "text") {
            text = valueOf(line, key);
        } else if (key == "decoded") {
            decoded = valueOf(line, key);
        } else if (key == "width") {
            fields >> width;
        } else if (key == "payload") {
            std::string value;
            fields >> value;
            payload = fromHex(value);
        } else if (key == "end") {
            if (mode == Mode::Encoding) {
                encodings[encodingKey] = building;
                continue;
            }

            const auto found = encodings.find(caseEncodingKey);
            if (found == encodings.end()) {
                report(name + " names an unknown encoding " + caseEncodingKey);
                continue;
            }
            const auto &encoding = found->second;

            if (mode == Mode::Case) {
                ++cases;
                try {
                    const auto encoded =
                        retrolarium::core::encodeText(text, width, encoding, name);
                    if (toHex(encoded) != toHex(payload)) {
                        report(name + " payload: got " + toHex(encoded) + ", wanted "
                            + toHex(payload));
                    }
                    const auto restored =
                        retrolarium::core::decodeText(encoded, encoding, name);
                    if (restored != decoded) {
                        report(name + " decoded: got \"" + restored + "\", wanted \""
                            + decoded + "\"");
                    }
                } catch (const retrolarium::core::NesTextError &error) {
                    report(name + " raised: " + error.what());
                }
            } else if (mode == Mode::Reject) {
                ++rejections;
                try {
                    static_cast<void>(
                        retrolarium::core::encodeText(text, width, encoding, name));
                    report(name + " was encoded but both sides must refuse it");
                } catch (const retrolarium::core::NesTextError &) {
                }
            } else if (mode == Mode::RejectDecode) {
                ++rejections;
                try {
                    static_cast<void>(
                        retrolarium::core::decodeText(payload, encoding, name));
                    report(name + " was decoded but both sides must refuse it");
                } catch (const retrolarium::core::NesTextError &) {
                }
            }
        } else {
            report("unknown corpus key \"" + key + "\"");
        }
    }

    if (cases == 0 || rejections == 0) {
        std::cerr << "corpus was missing cases or rejections\n";
        return 2;
    }
    if (failures != 0) {
        std::cerr << failures << " text parity check(s) failed\n";
        return 1;
    }
    std::cout << "NES text parity: " << cases << " cases, " << rejections
              << " rejections\n";
    return 0;
}
