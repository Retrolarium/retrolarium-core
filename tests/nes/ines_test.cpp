// Cross-language parity: the C++ iNES parser must agree with the Python
// oracle in retrolarium_core.ines. The corpus is produced by
// retrolarium-core/tools/generate-ines-golden.py.

#include <retrolarium/core/ines.hpp>
#include <retrolarium/core/sha256.hpp>

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

using retrolarium::core::InesError;
using retrolarium::core::mirroringName;
using retrolarium::core::parseInes;
using retrolarium::core::parseInesPrefix;

int failures = 0;

void check(bool condition, const std::string &what)
{
    if (!condition) {
        std::cerr << "FAIL: " << what << '\n';
        ++failures;
    }
}

template <typename T>
void checkEqual(const T &actual, const T &expected, const std::string &what)
{
    if (!(actual == expected)) {
        std::cerr << "FAIL: " << what << ": got " << actual << ", wanted "
                  << expected << '\n';
        ++failures;
    }
}

// Mirrors fill() in generate-ines-golden.py.
std::vector<std::uint8_t> fill(std::uint32_t seed, std::size_t size)
{
    std::uint32_t state = seed & 0x7FFFFFFFu;
    std::vector<std::uint8_t> out(size);
    for (std::size_t index = 0; index < size; ++index) {
        state = static_cast<std::uint32_t>(
            (static_cast<std::uint64_t>(state) * 1103515245u + 12345u) & 0x7FFFFFFFu);
        out[index] = static_cast<std::uint8_t>((state >> 16) & 0xFF);
    }
    return out;
}

std::vector<std::uint8_t> fromHex(const std::string &text)
{
    std::vector<std::uint8_t> out;
    out.reserve(text.size() / 2);
    const auto nibble = [](char character) -> int {
        if (character >= '0' && character <= '9') return character - '0';
        if (character >= 'a' && character <= 'f') return character - 'a' + 10;
        if (character >= 'A' && character <= 'F') return character - 'A' + 10;
        return -1;
    };
    for (std::size_t index = 0; index + 1 < text.size(); index += 2) {
        const int high = nibble(text[index]);
        const int low = nibble(text[index + 1]);
        if (high < 0 || low < 0) return {};
        out.push_back(static_cast<std::uint8_t>(high * 16 + low));
    }
    return out;
}

struct Case final {
    std::string name;
    std::vector<std::uint8_t> header;
    std::uint32_t bodySeed = 0;
    std::size_t bodySize = 0;
    std::string sha256;
    int mapper = 0;
    std::string mirroring;
    bool battery = false;
    std::size_t trainerSize = 0;
    std::size_t prgSize = 0;
    std::size_t chrSize = 0;
    std::vector<retrolarium::core::ImageRegion> regions;
    std::vector<std::uint8_t> prefixTrailer;
};

struct ErrorCase final {
    std::string name;
    std::vector<std::uint8_t> bytes;
    std::string needle;
};

void runCase(const Case &entry)
{
    std::vector<std::uint8_t> payload = entry.header;
    const auto body = fill(entry.bodySeed, entry.bodySize);
    payload.insert(payload.end(), body.begin(), body.end());

    retrolarium::core::InesImage image;
    try {
        image = parseInes(payload);
    } catch (const InesError &error) {
        std::cerr << "FAIL: " << entry.name << " did not parse: " << error.what()
                  << '\n';
        ++failures;
        return;
    }

    checkEqual(image.sha256, entry.sha256, entry.name + " sha256");
    checkEqual(image.mapper, entry.mapper, entry.name + " mapper");
    checkEqual(mirroringName(image.mirroring), entry.mirroring,
        entry.name + " mirroring");
    checkEqual(image.battery, entry.battery, entry.name + " battery");
    checkEqual(image.trainer.size(), entry.trainerSize, entry.name + " trainer size");
    checkEqual(image.prg.size(), entry.prgSize, entry.name + " prg size");
    checkEqual(image.chr.size(), entry.chrSize, entry.name + " chr size");

    const auto regions = image.regions();
    checkEqual(regions.size(), entry.regions.size(), entry.name + " region count");
    for (std::size_t index = 0; index < regions.size() && index < entry.regions.size();
        ++index) {
        const auto &actual = regions[index];
        const auto &expected = entry.regions[index];
        const std::string label = entry.name + " region " + expected.name;
        checkEqual(actual.name, expected.name, label + " name");
        checkEqual(actual.fileOffset, expected.fileOffset, label + " offset");
        checkEqual(actual.size, expected.size, label + " size");
        checkEqual(actual.sha256, expected.sha256, label + " sha256");
    }

    std::vector<std::uint8_t> extended = payload;
    extended.insert(
        extended.end(), entry.prefixTrailer.begin(), entry.prefixTrailer.end());
    try {
        const auto [prefixImage, rest] = parseInesPrefix(extended);
        checkEqual(prefixImage.sha256, entry.sha256, entry.name + " prefix sha256");
        check(rest == entry.prefixTrailer, entry.name + " prefix trailer");
    } catch (const InesError &error) {
        std::cerr << "FAIL: " << entry.name << " prefix parse: " << error.what() << '\n';
        ++failures;
    }
}

void runErrorCase(const ErrorCase &entry)
{
    try {
        static_cast<void>(parseInes(entry.bytes));
    } catch (const InesError &error) {
        const std::string message = error.what();
        check(message.find(entry.needle) != std::string::npos,
            entry.name + " error text: got \"" + message + "\", wanted \""
                + entry.needle + "\"");
        return;
    }
    std::cerr << "FAIL: " << entry.name << " unexpectedly parsed\n";
    ++failures;
}

} // namespace

int main(int argc, char *argv[])
{
    if (argc != 2) {
        std::cerr << "usage: retrolarium-core-ines-golden-tests <corpus.txt>\n";
        return 2;
    }

    std::ifstream stream(argv[1]);
    if (!stream) {
        std::cerr << "cannot open corpus " << argv[1] << '\n';
        return 2;
    }

    Case current;
    ErrorCase currentError;
    bool inCase = false;
    bool inError = false;
    int caseCount = 0;
    int errorCaseCount = 0;
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
            checkEqual(value, std::string {"retrolarium.ines-golden"}, "corpus schema");
        } else if (key == "schema_version") {
            int value = 0;
            fields >> value;
            checkEqual(value, 1, "corpus schema_version");
        } else if (key == "generator") {
            continue;
        } else if (key == "case") {
            current = Case {};
            fields >> current.name;
            inCase = true;
        } else if (key == "error-case") {
            currentError = ErrorCase {};
            fields >> currentError.name;
            inError = true;
        } else if (key == "header") {
            std::string value;
            fields >> value;
            current.header = fromHex(value);
        } else if (key == "body-seed") {
            fields >> current.bodySeed;
        } else if (key == "body-size") {
            fields >> current.bodySize;
        } else if (key == "expect-sha256") {
            fields >> current.sha256;
        } else if (key == "expect-mapper") {
            fields >> current.mapper;
        } else if (key == "expect-mirroring") {
            fields >> current.mirroring;
        } else if (key == "expect-battery") {
            int value = 0;
            fields >> value;
            current.battery = value != 0;
        } else if (key == "expect-trainer-size") {
            fields >> current.trainerSize;
        } else if (key == "expect-prg-size") {
            fields >> current.prgSize;
        } else if (key == "expect-chr-size") {
            fields >> current.chrSize;
        } else if (key == "region") {
            retrolarium::core::ImageRegion entry;
            fields >> entry.name >> entry.fileOffset >> entry.size >> entry.sha256;
            current.regions.push_back(entry);
        } else if (key == "expect-prefix-trailer") {
            std::string value;
            fields >> value;
            current.prefixTrailer = fromHex(value);
        } else if (key == "bytes") {
            std::string value;
            fields >> value;
            currentError.bytes = fromHex(value);
        } else if (key == "expect-error") {
            std::getline(fields, currentError.needle);
            if (!currentError.needle.empty() && currentError.needle.front() == ' ') {
                currentError.needle.erase(0, 1);
            }
        } else if (key == "end") {
            if (inCase) {
                runCase(current);
                ++caseCount;
                inCase = false;
            } else if (inError) {
                runErrorCase(currentError);
                ++errorCaseCount;
                inError = false;
            }
        } else {
            std::cerr << "FAIL: unknown corpus key \"" << key << "\"\n";
            ++failures;
        }
    }

    check(caseCount > 0, "corpus contained image cases");
    check(errorCaseCount > 0, "corpus contained error cases");

    if (failures != 0) {
        std::cerr << failures << " parity check(s) failed\n";
        return 1;
    }
    std::cout << "iNES parity: " << caseCount << " cases, " << errorCaseCount
              << " error cases\n";
    return 0;
}
