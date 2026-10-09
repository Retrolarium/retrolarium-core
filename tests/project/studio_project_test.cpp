// Cross-language parity for the Studio project contract.
//
// The corpus comes from tools/generate-studio-project-golden.py
// and is generated from the Kit's load_studio_project, which stays the oracle.
//
// Absolute paths differ on every machine, so both sides fold the fixture
// directory down to a <root> token before comparing.

#include <retrolarium/core/project/studio_project.hpp>

#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace {

// A UTF-8 BOM, written as bytes so the constant does not depend on the
// source file's own encoding.
const std::string kBom {char(0xEF), char(0xBB), char(0xBF)};

const std::string kRootToken = "<root>";

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

// Windows separators reach the projection through the filesystem, while the
// corpus stores the portable form.
std::string toPosix(std::string value)
{
    for (char &character : value) {
        if (character == '\\') character = '/';
    }
    return value;
}

std::string foldRoot(const std::string &value, const std::string &root)
{
    if (value.empty()) return value;
    const std::string posix = toPosix(value);
    if (posix == root) return kRootToken;
    if (posix.size() > root.size() && posix.compare(0, root.size(), root) == 0
        && posix[root.size()] == '/') {
        return kRootToken + posix.substr(root.size());
    }
    return posix;
}

} // namespace

int main(int argc, char *argv[])
{
    if (argc != 3) {
        std::cerr << "usage: retrolarium-core-studio-project-golden-tests"
                     " <corpus.txt> <fixtures-dir>\n";
        return 2;
    }

    std::ifstream stream(argv[1]);
    if (!stream) {
        std::cerr << "cannot open corpus " << argv[1] << '\n';
        return 2;
    }
    const std::string fixtures = toPosix(argv[2]);

    // The corpus was produced against the resolved fixture directory, so the
    // root the test folds away has to be resolved the same way. Loading any
    // fixture yields it.
    std::string root;
    try {
        root = toPosix(
            retrolarium::core::loadStudioProject(fixtures + "/accept-minimal.rlj")
                .projectRoot);
    } catch (const retrolarium::core::StudioProjectError &error) {
        std::cerr << "cannot resolve the fixture root: " << error.what() << '\n';
        return 2;
    }

    std::string caseName;
    bool rejecting = false;
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
            if (value != "retrolarium.studio-project-golden") {
                report("unexpected corpus schema " + value);
            }
        } else if (key == "schema_version" || key == "generator"
            || key == "fixtures") {
            continue;
        } else if (key == "accept" || key == "reject") {
            caseName = value;
            rejecting = key == "reject";
            expected.clear();
        } else if (key == "projection" || key == "message") {
            expected = fromHex(value);
        } else if (key == "end") {
            const std::string path = fixtures + "/" + caseName;
            if (rejecting) {
                ++rejected;
                try {
                    static_cast<void>(retrolarium::core::loadStudioProject(path));
                    report(caseName + " was accepted; the Kit refuses it with \""
                        + expected + "\"");
                } catch (const retrolarium::core::StudioProjectError &error) {
                    // A TOML syntax error is worded differently on each side by
                    // design, so only contract refusals are compared verbatim.
                    const std::string actual = error.what();
                    if (actual != expected) {
                        report(caseName + " refused with \"" + actual
                            + "\", the Kit says \"" + expected + "\"");
                    }
                }
                continue;
            }

            ++accepted;
            try {
                retrolarium::core::StudioInspection inspection =
                    retrolarium::core::loadStudioProject(path);
                inspection.projectFile = foldRoot(inspection.projectFile, root);
                inspection.projectRoot = foldRoot(inspection.projectRoot, root);
                inspection.disassemblyPath =
                    foldRoot(inspection.disassemblyPath, root);
                for (retrolarium::core::StudioTab &tab : inspection.tabs) {
                    tab.documentPath = foldRoot(tab.documentPath, root);
                }

                const std::string actual =
                    retrolarium::core::renderStudioInspection(inspection);
                if (actual != expected) {
                    report(caseName + " projected:\n" + actual + "\nwanted:\n"
                        + expected);
                }
            } catch (const retrolarium::core::StudioProjectError &error) {
                report(caseName + " raised: " + error.what());
            }
        } else {
            report("unknown corpus key \"" + key + "\"");
        }
    }

    // A file that is not a project at all must be refused on its extension
    // rather than parsed.
    {
        ++rejected;
        try {
            static_cast<void>(retrolarium::core::loadStudioProject(
                fixtures + "/documents/levels.toml"));
            report("a .toml file was accepted as a project");
        } catch (const retrolarium::core::StudioProjectError &) {
        }
    }

    if (accepted == 0) {
        std::cerr << "corpus carried no projects\n";
        return 2;
    }
    if (failures != 0) {
        std::cerr << failures << " studio project parity check(s) failed\n";
        return 1;
    }
    std::cout << "Studio project parity: " << accepted << " projects, " << rejected
              << " refusals\n";
    return 0;
}
