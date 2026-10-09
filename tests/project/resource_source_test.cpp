// Cross-language parity for turning a resource into bytes.
//
// The corpus comes from tools/generate-resource-source-golden.py
// and is generated from the Kit's own helpers in nes_resources, which stay the
// oracle.
//
// The ROM image is described rather than carried; both sides build it and
// compare its SHA-256 first, so a builder that drifted fails there rather than
// further down.

#include <retrolarium/core/resource_source.hpp>
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

int failures = 0;

void report(const std::string &message)
{
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
}

std::string fromHex(const std::string &text)
{
    const auto nibble = [](char character) -> int {
        if (character >= '0' && character <= '9') return character - '0';
        if (character >= 'a' && character <= 'f') return character - 'a' + 10;
        if (character >= 'A' && character <= 'F') return character - 'A' + 10;
        return -1;
    };
    std::string out;
    for (std::size_t index = 0; index + 1 < text.size(); index += 2) {
        const int high = nibble(text[index]);
        const int low = nibble(text[index + 1]);
        if (high < 0 || low < 0) return {};
        out.push_back(static_cast<char>(high * 16 + low));
    }
    return out;
}

std::vector<std::string> split(const std::string &text, char separator)
{
    std::vector<std::string> parts;
    std::istringstream stream(text);
    std::string item;
    while (std::getline(stream, item, separator)) {
        parts.push_back(item);
    }
    return parts;
}

// Mirrors build_image in the generator.
std::vector<std::uint8_t> buildImage(std::size_t headerSize, std::size_t total)
{
    std::vector<std::uint8_t> image(total, 0);
    image[0] = 'N';
    image[1] = 'E';
    image[2] = 'S';
    image[3] = 0x1A;
    image[4] = 2;
    for (std::size_t index = 0; index + headerSize < total; ++index) {
        image[headerSize + index] = static_cast<std::uint8_t>((index * 7 + 13) & 0xFF);
    }
    return image;
}

std::vector<retrolarium::core::ResourceSpan> parseSpans(const std::string &text)
{
    std::vector<retrolarium::core::ResourceSpan> spans;
    for (const std::string &item : split(text, ';')) {
        if (item.empty()) continue;
        // A trailing empty field means "the source image", so the split has to
        // keep it; getline drops it, hence the manual scan.
        const std::size_t first = item.find(',');
        const std::size_t second = item.find(',', first + 1);
        if (first == std::string::npos || second == std::string::npos) continue;
        retrolarium::core::ResourceSpan span;
        span.offset = static_cast<std::size_t>(std::stoul(item.substr(0, first)));
        span.size = static_cast<std::size_t>(
            std::stoul(item.substr(first + 1, second - first - 1)));
        span.payloadId = item.substr(second + 1);
        spans.push_back(std::move(span));
    }
    return spans;
}

const retrolarium::core::ResourceSpec *findResource(
    const std::vector<retrolarium::core::ResourceSpec> &resources,
    const std::string &id)
{
    for (const retrolarium::core::ResourceSpec &resource : resources) {
        if (resource.resourceId == id) return &resource;
    }
    return nullptr;
}

} // namespace

int main(int argc, char *argv[])
{
    if (argc != 2) {
        std::cerr << "usage: retrolarium-core-resource-source-golden-tests"
                     " <corpus.txt>\n";
        return 2;
    }
    std::ifstream stream(argv[1]);
    if (!stream) {
        std::cerr << "cannot open corpus " << argv[1] << '\n';
        return 2;
    }

    std::string imageSha;
    std::size_t imageSize = 0;
    std::size_t prgOffset = 0;
    std::vector<std::uint8_t> image;
    retrolarium::core::GameProfile profile;
    bool haveProfile = false;

    enum class Mode { None, Case, Reject, ParameterSpan, Replicated, Source };
    Mode mode = Mode::None;
    std::string caseName;
    std::string resourceId;
    std::vector<retrolarium::core::ResourceSpan> spans;
    std::string readSha;
    std::size_t readSize = 0;
    std::string encodedText;
    std::string message;
    std::size_t expectedSize = 0;
    std::string resolvedText;
    std::size_t entries = 0;
    std::string offsetsText;
    std::string sourceSha;
    retrolarium::core::GameProfile caseProfile;
    bool haveCaseProfile = false;

    int checks = 0;
    int rejected = 0;
    std::string line;
    bool firstLine = true;

    while (std::getline(stream, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (firstLine && line.rfind(kBom, 0) == 0) line.erase(0, kBom.size());
        firstLine = false;
        if (line.empty()) continue;

        const std::size_t space = line.find(' ');
        const std::string key = line.substr(0, space);
        const std::string value =
            space == std::string::npos ? std::string() : line.substr(space + 1);

        if (key == "schema") {
            if (value != "retrolarium.resource-source-golden") {
                report("unexpected corpus schema " + value);
            }
        } else if (key == "schema_version" || key == "generator") {
            continue;
        } else if (key == "image-sha256") {
            imageSha = value;
        } else if (key == "image-size") {
            imageSize = static_cast<std::size_t>(std::stoul(value));
        } else if (key == "prg-offset") {
            prgOffset = static_cast<std::size_t>(std::stoul(value));
            image = buildImage(prgOffset, imageSize);
            if (retrolarium::core::sha256Hex(image) != imageSha) {
                std::cerr << "the two builders disagree on the ROM image\n";
                return 1;
            }
        } else if (key == "profile") {
            if (mode == Mode::Reject) {
                caseProfile = retrolarium::core::parseGameProfile(fromHex(value));
                haveCaseProfile = true;
            } else {
                profile = retrolarium::core::parseGameProfile(fromHex(value));
                haveProfile = true;
            }
        } else if (key == "container-mapper") {
            ++checks;
            const auto container = retrolarium::core::validateRevisionContainer(
                image, profile.revisions.at(0));
            if (!container.hasMapper
                || container.mapper != std::stoi(value)) {
                report("container mapper differs from the Kit's");
            }
        } else if (key == "case" || key == "reject") {
            caseName = value;
            mode = key == "case" ? Mode::Case : Mode::Reject;
            haveCaseProfile = false;
            spans.clear();
            encodedText.clear();
            message.clear();
        } else if (key == "parameter-span") {
            mode = Mode::ParameterSpan;
            caseName = value;
            resourceId = value;
        } else if (key == "replicated") {
            mode = Mode::Replicated;
            caseName = value;
            resourceId = value;
        } else if (key == "resource-source") {
            mode = Mode::Source;
            caseName = value;
            resourceId = value;
        } else if (key == "resource") {
            resourceId = value;
        } else if (key == "spans") {
            spans = parseSpans(value);
        } else if (key == "read-sha256") {
            readSha = value;
        } else if (key == "read-size") {
            readSize = static_cast<std::size_t>(std::stoul(value));
        } else if (key == "encoded") {
            encodedText = value;
        } else if (key == "message") {
            message = fromHex(value);
        } else if (key == "expected") {
            expectedSize = static_cast<std::size_t>(std::stoul(value));
        } else if (key == "resolved") {
            resolvedText = value;
        } else if (key == "entries") {
            entries = static_cast<std::size_t>(std::stoul(value));
        } else if (key == "offsets") {
            offsetsText = value;
        } else if (key == "sha256") {
            sourceSha = value;
        } else if (key == "end") {
            if (!haveProfile) {
                report("the corpus did not carry a profile");
                continue;
            }
            const retrolarium::core::GameProfile &active =
                haveCaseProfile ? caseProfile : profile;
            const retrolarium::core::RevisionSpec &revision =
                active.revisions.at(0);
            const std::vector<retrolarium::core::ResourceSpec> resources =
                active.resourcesFor(revision);
            const retrolarium::core::ResourceSpec *resource =
                findResource(resources, resourceId);
            if (resource == nullptr) {
                report(caseName + ": unknown resource " + resourceId);
                continue;
            }

            try {
                if (mode == Mode::Reject) {
                    ++rejected;
                    try {
                        static_cast<void>(retrolarium::core::readResourceSpans(
                            image, active, revision, *resource, spans));
                        report(caseName + " was read; the Kit refuses it: "
                            + message);
                    } catch (const std::exception &error) {
                        const std::string actual = error.what();
                        if (actual != message) {
                            report(caseName + " refused with [" + actual
                                + "], the Kit says [" + message + "]");
                        }
                    }
                } else if (mode == Mode::Case) {
                    ++checks;
                    const auto read = retrolarium::core::readResourceSpans(
                        image, active, revision, *resource, spans);
                    if (read.size() != readSize) {
                        report(caseName + " read " + std::to_string(read.size())
                            + " bytes, wanted " + std::to_string(readSize));
                    }
                    if (retrolarium::core::sha256Hex(read) != readSha) {
                        report(caseName + " read different bytes");
                    }
                    const auto encoded =
                        retrolarium::core::encodedResourceSpans(read, spans);
                    std::ostringstream rendered;
                    for (std::size_t index = 0; index < encoded.size(); ++index) {
                        if (index != 0) rendered << ';';
                        rendered << encoded[index].offset << ','
                                 << encoded[index].replacement.size() << ','
                                 << encoded[index].payloadId;
                    }
                    if (rendered.str() != encodedText) {
                        report(caseName + " encoded [" + rendered.str()
                            + "], wanted [" + encodedText + "]");
                    }
                } else if (mode == Mode::ParameterSpan) {
                    ++checks;
                    const auto span = retrolarium::core::resourceParameterSpan(
                        *resource, expectedSize);
                    std::ostringstream rendered;
                    rendered << span.offset << ' ' << span.size;
                    if (rendered.str() != resolvedText) {
                        report(caseName + " resolved [" + rendered.str()
                            + "], wanted [" + resolvedText + "]");
                    }
                } else if (mode == Mode::Replicated) {
                    ++checks;
                    bool declared = false;
                    const auto offsets =
                        retrolarium::core::replicatedPaletteOffsets(
                            *resource, entries, declared);
                    if (!declared) {
                        report(caseName + " reported no replicated offsets");
                    }
                    std::ostringstream rendered;
                    for (std::size_t entry = 0; entry < offsets.size(); ++entry) {
                        if (entry != 0) rendered << ';';
                        for (std::size_t index = 0;
                            index < offsets[entry].size(); ++index) {
                            if (index != 0) rendered << ',';
                            rendered << offsets[entry][index];
                        }
                    }
                    if (rendered.str() != offsetsText) {
                        report(caseName + " offsets [" + rendered.str()
                            + "], wanted [" + offsetsText + "]");
                    }
                } else if (mode == Mode::Source) {
                    ++checks;
                    const auto bytes = retrolarium::core::resourceSource(
                        image, active, revision, *resource);
                    if (retrolarium::core::sha256Hex(bytes) != sourceSha) {
                        report(caseName + " sourced different bytes");
                    }
                }
            } catch (const std::exception &error) {
                report(caseName + " raised: " + error.what());
            }
            mode = Mode::None;
        } else {
            report("unknown corpus key \"" + key + "\"");
        }
    }

    if (checks == 0) {
        std::cerr << "corpus carried no checks\n";
        return 2;
    }
    if (failures != 0) {
        std::cerr << failures << " resource source parity check(s) failed\n";
        return 1;
    }
    std::cout << "Resource source parity: " << checks << " checks, " << rejected
              << " refusals\n";
    return 0;
}
