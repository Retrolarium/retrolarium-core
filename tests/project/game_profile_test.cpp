// Cross-language parity for the game-profile contract.
//
// The corpus comes from retrolarium_core/tools/generate-game-profile-golden.py
// and is generated from the Kit's parse_game_profile, which stays the oracle.
//
// Accepted profiles are the packaged ones, copied into the fixtures beside
// their expected projections so the core's tests stay self-contained. Refused
// ones are mutations of a small synthetic profile and travel inside the corpus,
// so both loaders are handed the same bytes.

#include <retrolarium/core/game_profile.hpp>

#include <fstream>
#include <iostream>
#include <sstream>
#include <string>

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
    out.reserve(text.size() / 2);
    for (std::size_t index = 0; index + 1 < text.size(); index += 2) {
        const int high = nibble(text[index]);
        const int low = nibble(text[index + 1]);
        if (high < 0 || low < 0) return {};
        out.push_back(static_cast<char>(high * 16 + low));
    }
    return out;
}

std::string readFile(const std::string &path)
{
    std::ifstream stream(path, std::ios::binary);
    if (!stream) return {};
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    return buffer.str();
}

// The expected projections are stored with a trailing newline so they read as
// ordinary text files; the renderer does not produce one.
std::string withoutTrailingNewline(std::string value)
{
    while (!value.empty() && (value.back() == '\n' || value.back() == '\r')) {
        value.pop_back();
    }
    return value;
}

std::string stem(const std::string &name)
{
    const std::size_t dot = name.rfind('.');
    return dot == std::string::npos ? name : name.substr(0, dot);
}

} // namespace

int main(int argc, char *argv[])
{
    if (argc != 3) {
        std::cerr << "usage: retrolarium-core-game-profile-golden-tests"
                     " <corpus.txt> <fixtures-dir>\n";
        return 2;
    }

    std::ifstream stream(argv[1]);
    if (!stream) {
        std::cerr << "cannot open corpus " << argv[1] << '\n';
        return 2;
    }
    const std::string fixtures = argv[2];

    enum class Mode { None, Accept, AcceptInline, Reject };
    Mode mode = Mode::None;
    std::string caseName;
    std::string source;
    std::string expected;

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
            if (value != "retrolarium.game-profile-golden") {
                report("unexpected corpus schema " + value);
            }
        } else if (key == "schema_version" || key == "generator") {
            continue;
        } else if (key == "accept" || key == "accept-inline" || key == "reject") {
            caseName = value;
            mode = key == "accept" ? Mode::Accept
                : key == "accept-inline" ? Mode::AcceptInline : Mode::Reject;
            source.clear();
            expected.clear();
        } else if (key == "source") {
            source = fromHex(value);
        } else if (key == "projection") {
            expected = fromHex(value);
        } else if (key == "message") {
            expected = fromHex(value);
        } else if (key == "end") {
            if (mode == Mode::Reject) {
                ++rejected;
                try {
                    static_cast<void>(
                        retrolarium::core::parseGameProfile(source));
                    report(caseName + " was accepted; the Kit refuses it with: "
                        + expected);
                } catch (const retrolarium::core::AuthoringError &error) {
                    const std::string actual = error.what();
                    if (actual != expected) {
                        report(caseName + " refused with [" + actual
                            + "], the Kit says [" + expected + "]");
                    }
                }
                continue;
            }

            ++accepted;
            std::string wanted = expected;
            try {
                retrolarium::core::GameProfile profile;
                if (mode == Mode::Accept) {
                    const std::string path = fixtures + "/" + caseName;
                    profile = retrolarium::core::loadGameProfile(path);
                    wanted = withoutTrailingNewline(readFile(
                        fixtures + "/" + stem(caseName) + ".projection.json"));
                    if (wanted.empty()) {
                        report(caseName + ": the expected projection is missing");
                        continue;
                    }
                } else {
                    profile = retrolarium::core::parseGameProfile(source);
                }

                const std::string actual =
                    retrolarium::core::renderGameProfile(profile);
                if (actual != wanted) {
                    report(caseName + " projected " + std::to_string(actual.size())
                        + " bytes, wanted " + std::to_string(wanted.size())
                        + "; regenerate the corpus to see the difference");
                }
            } catch (const retrolarium::core::AuthoringError &error) {
                report(caseName + " raised: " + error.what());
            }
        } else {
            report("unknown corpus key \"" + key + "\"");
        }
    }

    // A document that is not JSON at all must be refused rather than read as
    // an empty profile.
    {
        ++rejected;
        try {
            static_cast<void>(retrolarium::core::parseGameProfile("{"));
            report("a truncated document was accepted");
        } catch (const retrolarium::core::AuthoringError &) {
        }
    }

    if (accepted == 0) {
        std::cerr << "corpus carried no profiles\n";
        return 2;
    }
    if (failures != 0) {
        std::cerr << failures << " game profile parity check(s) failed\n";
        return 1;
    }
    std::cout << "Game profile parity: " << accepted << " profiles, " << rejected
              << " refusals\n";
    return 0;
}
