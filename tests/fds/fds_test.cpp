// Cross-language parity for the raw FDS side.
//
// The corpus comes from retrolarium_core/tools/generate-fds-golden.py and is
// generated from retrolarium_kit.fds, which stays the oracle.
//
// A side is 65500 bytes, so the corpus describes one rather than carrying it.
// Both sides build the image from that description and compare its SHA-256
// before anything else, so a builder that drifted fails here rather than
// producing a misleading mismatch further down.

#include <retrolarium/core/fds.hpp>
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

constexpr std::size_t kSideSize = 65500;

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

struct FileSpec {
    int fileId = 0;
    std::size_t size = 0;
    std::uint8_t fill = 0;
};

std::vector<FileSpec> parseFiles(const std::string &text)
{
    std::vector<FileSpec> files;
    for (const std::string &item : split(text, ';')) {
        const std::vector<std::string> parts = split(item, ':');
        if (parts.size() != 3) continue;
        FileSpec spec;
        spec.fileId = std::stoi(parts[0]);
        spec.size = static_cast<std::size_t>(std::stoul(parts[1]));
        spec.fill = static_cast<std::uint8_t>(std::stoi(parts[2]));
        files.push_back(spec);
    }
    return files;
}

// Mirrors build_side in the generator, defect for defect.
std::vector<std::uint8_t> buildSide(
    const std::vector<FileSpec> &files, const std::string &corrupt)
{
    std::vector<std::uint8_t> image(kSideSize, 0);
    image[0] = corrupt == "block1" ? 9 : 1;
    for (std::size_t index = 1; index < 56; ++index) {
        image[index] = 0x5A;
    }
    image[56] = corrupt == "block2" ? 9 : 2;
    image[57] = static_cast<std::uint8_t>(
        corrupt == "file-count" ? files.size() + 1 : files.size());

    std::size_t position = 58;
    for (std::size_t number = 0; number < files.size(); ++number) {
        const FileSpec &spec = files[number];
        std::vector<std::uint8_t> header(16, 0);
        header[0] = corrupt == "block3" ? 9 : 3;
        header[1] = static_cast<std::uint8_t>(number);
        header[2] = static_cast<std::uint8_t>(spec.fileId);
        std::ostringstream name;
        name << "FILE" << std::string(4 - std::to_string(number).size(), '0')
             << number;
        const std::string text = name.str();
        for (std::size_t index = 0; index < 8 && index < text.size(); ++index) {
            header[3 + index] = static_cast<std::uint8_t>(text[index]);
        }
        header[11] = 0x00;
        header[12] = 0x60;
        header[13] = static_cast<std::uint8_t>(spec.size & 0xFF);
        header[14] = static_cast<std::uint8_t>((spec.size >> 8) & 0xFF);
        if (corrupt == "oversize" && number == 0) {
            header[13] = 0xFF;
            header[14] = 0xFF;
        }
        header[15] = 1;
        std::copy(header.begin(), header.end(),
            image.begin() + static_cast<std::ptrdiff_t>(position));
        position += 16;
        image[position] = corrupt == "block4" ? 9 : 4;
        position += 1;
        for (std::size_t index = 0; index < spec.size; ++index) {
            image[position + index] = spec.fill;
        }
        position += spec.size;
    }

    if (corrupt == "trailing") {
        image[kSideSize - 1] = 0xFF;
    }
    return image;
}

} // namespace

int main(int argc, char *argv[])
{
    if (argc != 2) {
        std::cerr << "usage: retrolarium-core-fds-golden-tests <corpus.txt>\n";
        return 2;
    }
    std::ifstream stream(argv[1]);
    if (!stream) {
        std::cerr << "cannot open corpus " << argv[1] << '\n';
        return 2;
    }

    std::string caseName;
    bool rejecting = false;
    std::vector<FileSpec> files;
    std::string corrupt;
    std::string sideSha;
    std::string recordsText;
    std::string namesText;
    std::vector<int> select;
    std::string payloadSha;
    std::size_t payloadSize = 0;
    std::size_t rangeOffset = 0;
    std::size_t rangeSize = 0;
    std::string rangesText;
    std::string replacedSha;
    std::string message;

    int accepted = 0;
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
            if (value != "retrolarium.fds-golden") {
                report("unexpected corpus schema " + value);
            }
        } else if (key == "schema_version" || key == "generator") {
            continue;
        } else if (key == "case" || key == "reject") {
            caseName = value;
            rejecting = key == "reject";
            files.clear();
            corrupt.clear();
            select.clear();
            recordsText.clear();
            namesText.clear();
            rangesText.clear();
            message.clear();
        } else if (key == "files") {
            files = parseFiles(value);
        } else if (key == "corrupt") {
            corrupt = value;
        } else if (key == "side-sha256") {
            sideSha = value;
        } else if (key == "records") {
            recordsText = value;
        } else if (key == "names") {
            namesText = value;
        } else if (key == "select") {
            select.clear();
            for (const std::string &item : split(value, ',')) {
                if (!item.empty()) select.push_back(std::stoi(item));
            }
        } else if (key == "payload-sha256") {
            payloadSha = value;
        } else if (key == "payload-size") {
            payloadSize = static_cast<std::size_t>(std::stoul(value));
        } else if (key == "range-request") {
            std::istringstream request(value);
            request >> rangeOffset >> rangeSize;
        } else if (key == "ranges") {
            rangesText = value;
        } else if (key == "replaced-sha256") {
            replacedSha = value;
        } else if (key == "message") {
            message = fromHex(value);
        } else if (key == "end") {
            const std::vector<std::uint8_t> image = buildSide(files, corrupt);
            if (retrolarium::core::sha256Hex(image) != sideSha) {
                report(caseName + ": the two builders disagree on the side bytes");
                continue;
            }

            if (rejecting) {
                ++rejected;
                try {
                    static_cast<void>(retrolarium::core::parseFdsSide(image));
                    report(caseName + " parsed; the Kit refuses it: " + message);
                } catch (const retrolarium::core::FdsError &error) {
                    const std::string actual = error.what();
                    if (actual != message) {
                        report(caseName + " refused with [" + actual
                            + "], the Kit says [" + message + "]");
                    }
                }
                continue;
            }

            ++accepted;
            try {
                const auto records = retrolarium::core::parseFdsSide(image);
                std::ostringstream rendered;
                std::ostringstream names;
                for (std::size_t index = 0; index < records.size(); ++index) {
                    const auto &record = records[index];
                    if (index != 0) {
                        rendered << ';';
                        names << ';';
                    }
                    rendered << record.fileNumber << ',' << record.fileId << ','
                             << record.loadAddress << ',' << record.size << ','
                             << record.fileType << ',' << record.headerOffset << ','
                             << record.dataOffset;
                    names << toHex(record.name);
                }
                if (rendered.str() != recordsText) {
                    report(caseName + " records [" + rendered.str() + "], wanted ["
                        + recordsText + "]");
                }
                if (names.str() != namesText) {
                    report(caseName + " names [" + names.str() + "], wanted ["
                        + namesText + "]");
                }

                const auto payload = retrolarium::core::fdsPayload(image, select);
                if (payload.size() != payloadSize) {
                    report(caseName + " payload is " + std::to_string(payload.size())
                        + " bytes, wanted " + std::to_string(payloadSize));
                }
                if (retrolarium::core::sha256Hex(payload) != payloadSha) {
                    report(caseName + " payload bytes differ");
                }

                const auto ranges = retrolarium::core::fdsPayloadRanges(
                    image, select, rangeOffset, rangeSize);
                std::ostringstream renderedRanges;
                for (std::size_t index = 0; index < ranges.size(); ++index) {
                    if (index != 0) renderedRanges << ';';
                    renderedRanges << ranges[index].fileOffset << ','
                                   << ranges[index].payloadOffset << ','
                                   << ranges[index].size;
                }
                if (renderedRanges.str() != rangesText) {
                    report(caseName + " ranges [" + renderedRanges.str()
                        + "], wanted [" + rangesText + "]");
                }

                const std::vector<std::uint8_t> blank(payloadSize, 0);
                const auto replaced =
                    retrolarium::core::replaceFdsPayload(image, select, blank);
                if (retrolarium::core::sha256Hex(replaced) != replacedSha) {
                    report(caseName + " replacement changed the wrong bytes");
                }
            } catch (const retrolarium::core::FdsError &error) {
                report(caseName + " raised: " + error.what());
            }
        } else {
            report("unknown corpus key \"" + key + "\"");
        }
    }

    // A payload naming the same file twice is refused rather than duplicated.
    {
        ++rejected;
        const std::vector<FileSpec> pair {{0x10, 16, 0xAA}, {0x11, 16, 0xBB}};
        const auto image = buildSide(pair, "");
        try {
            static_cast<void>(
                retrolarium::core::fdsPayload(image, {0x10, 0x10}));
            report("a repeated record id was accepted");
        } catch (const retrolarium::core::FdsError &) {
        }
    }

    if (accepted == 0) {
        std::cerr << "corpus carried no sides\n";
        return 2;
    }
    if (failures != 0) {
        std::cerr << failures << " FDS parity check(s) failed\n";
        return 1;
    }
    std::cout << "FDS parity: " << accepted << " sides, " << rejected
              << " refusals\n";
    return 0;
}
