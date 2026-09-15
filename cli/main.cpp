// rlcore: the command-line face of retrolarium_core.
//
// The same library is linked straight into the Qt application, so this file
// stays a thin argument parser. Anything with real logic belongs in the
// library, where both consumers and the tests reach it.

#include <retrolarium/core/ines.hpp>
#include <retrolarium/core/sha256.hpp>

#include <iostream>
#include <string>
#include <vector>

namespace {

constexpr char kVersion[] = "0.1.0";

void printUsage(std::ostream &out)
{
    out << "usage: rlcore <command> [arguments]\n"
           "\n"
           "commands:\n"
           "  ines inspect <image.nes>   report container layout as JSON\n"
           "  version                    print the core version\n";
}

std::string jsonEscape(const std::string &value)
{
    std::string out;
    out.reserve(value.size() + 2);
    for (const char character : value) {
        switch (character) {
        case '"':
            out += "\\\"";
            break;
        case '\\':
            out += "\\\\";
            break;
        case '\n':
            out += "\\n";
            break;
        case '\r':
            out += "\\r";
            break;
        case '\t':
            out += "\\t";
            break;
        default:
            out.push_back(character);
        }
    }
    return out;
}

int inesInspect(const std::string &path)
{
    const auto image = retrolarium::core::loadInes(path);
    std::cout << "{\n";
    std::cout << "  \"schema\": \"retrolarium.ines-inspection\",\n";
    std::cout << "  \"schema_version\": 1,\n";
    std::cout << "  \"source\": \"" << jsonEscape(path) << "\",\n";
    std::cout << "  \"sha256\": \"" << image.sha256 << "\",\n";
    std::cout << "  \"size\": " << image.data.size() << ",\n";
    std::cout << "  \"mapper\": " << image.mapper << ",\n";
    std::cout << "  \"mirroring\": \"" << retrolarium::core::mirroringName(
        image.mirroring) << "\",\n";
    std::cout << "  \"battery\": " << (image.battery ? "true" : "false") << ",\n";
    std::cout << "  \"regions\": [\n";
    const auto regions = image.regions();
    for (std::size_t index = 0; index < regions.size(); ++index) {
        const auto &entry = regions[index];
        std::cout << "    {\"name\": \"" << entry.name << "\", \"file_offset\": "
                  << entry.fileOffset << ", \"size\": " << entry.size
                  << ", \"sha256\": \"" << entry.sha256 << "\"}"
                  << (index + 1 < regions.size() ? "," : "") << '\n';
    }
    std::cout << "  ]\n";
    std::cout << "}\n";
    return 0;
}

} // namespace

int main(int argc, char *argv[])
{
    const std::vector<std::string> arguments(argv + 1, argv + argc);
    if (arguments.empty() || arguments[0] == "-h" || arguments[0] == "--help") {
        printUsage(arguments.empty() ? std::cerr : std::cout);
        return arguments.empty() ? 2 : 0;
    }

    try {
        if (arguments[0] == "version") {
            std::cout << kVersion << '\n';
            return 0;
        }
        if (arguments[0] == "ines") {
            if (arguments.size() == 3 && arguments[1] == "inspect") {
                return inesInspect(arguments[2]);
            }
            std::cerr << "rlcore: ines takes 'inspect <image.nes>'\n";
            return 2;
        }
    } catch (const retrolarium::core::InesError &error) {
        std::cerr << "rlcore: " << error.what() << '\n';
        return 1;
    }

    std::cerr << "rlcore: unknown command '" << arguments[0] << "'\n";
    printUsage(std::cerr);
    return 2;
}
