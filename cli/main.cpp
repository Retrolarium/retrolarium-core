// rlcore: the command-line face of retrolarium_core.
//
// The same library is linked straight into the Qt application, so this file
// stays a thin argument parser. Anything with real logic belongs in the
// library, where both consumers and the tests reach it.

#include <retrolarium/core/megadrive/enigma.hpp>
#include <retrolarium/core/nes/ines.hpp>
#include <retrolarium/core/megadrive/nemesis.hpp>
#include <retrolarium/core/hash/sha256.hpp>

#include <cstdint>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace {

constexpr char kVersion[] = "0.1.0";

class UsageError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

void printUsage(std::ostream &out)
{
    out << "usage: rlcore <command> [arguments]\n"
           "\n"
           "commands:\n"
           "  ines inspect <image.nes>\n"
           "      report container layout as JSON\n"
           "  nemesis decompress <in.nem> <out.bin>\n"
           "  nemesis compress <plain.bin> <reference.nem> <out.nem>\n"
           "      re-encode using the reference's own code table\n"
           "  enigma decompress <in.eni> <out.bin> [base-tile]\n"
           "  enigma compress <plain.bin> <out.eni>\n"
           "  version\n";
}

std::vector<std::uint8_t> readFile(const std::string &path)
{
    std::ifstream stream(path, std::ios::binary);
    if (!stream) {
        throw UsageError("cannot read " + path);
    }
    return {std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>()};
}

void writeFile(const std::string &path, const std::vector<std::uint8_t> &data)
{
    std::ofstream stream(path, std::ios::binary);
    if (!stream) {
        throw UsageError("cannot write " + path);
    }
    stream.write(reinterpret_cast<const char *>(data.data()),
        static_cast<std::streamsize>(data.size()));
    if (!stream) {
        throw UsageError("failed while writing " + path);
    }
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
    std::cout << "  \"mirroring\": \""
              << retrolarium::core::mirroringName(image.mirroring) << "\",\n";
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

// Reports what was written so a caller can log or check it without re-reading
// the file.
void reportWritten(const std::string &path, std::size_t bytes)
{
    std::cout << "{\"schema\": \"retrolarium.codec-result\", \"schema_version\": 1, "
              << "\"output\": \"" << jsonEscape(path) << "\", \"size\": " << bytes
              << "}\n";
}

int nemesisCommand(const std::vector<std::string> &arguments)
{
    if (arguments.size() == 4 && arguments[1] == "decompress") {
        const auto out = retrolarium::core::nemesisDecompress(readFile(arguments[2]));
        writeFile(arguments[3], out);
        reportWritten(arguments[3], out.size());
        return 0;
    }
    if (arguments.size() == 5 && arguments[1] == "compress") {
        const auto out = retrolarium::core::nemesisCompress(
            readFile(arguments[2]), readFile(arguments[3]));
        writeFile(arguments[4], out);
        reportWritten(arguments[4], out.size());
        return 0;
    }
    throw UsageError("nemesis takes 'decompress <in> <out>' or "
                     "'compress <plain> <reference> <out>'");
}

int enigmaCommand(const std::vector<std::string> &arguments)
{
    if ((arguments.size() == 4 || arguments.size() == 5)
        && arguments[1] == "decompress") {
        int baseTile = 0;
        if (arguments.size() == 5) {
            try {
                baseTile = std::stoi(arguments[4], nullptr, 0);
            } catch (const std::exception &) {
                throw UsageError("base-tile must be an integer");
            }
        }
        const auto out =
            retrolarium::core::enigmaDecompress(readFile(arguments[2]), baseTile);
        writeFile(arguments[3], out);
        reportWritten(arguments[3], out.size());
        return 0;
    }
    if (arguments.size() == 4 && arguments[1] == "compress") {
        const auto out = retrolarium::core::enigmaCompress(readFile(arguments[2]));
        writeFile(arguments[3], out);
        reportWritten(arguments[3], out.size());
        return 0;
    }
    throw UsageError("enigma takes 'decompress <in> <out> [base-tile]' or "
                     "'compress <plain> <out>'");
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
            throw UsageError("ines takes 'inspect <image.nes>'");
        }
        if (arguments[0] == "nemesis") {
            return nemesisCommand(arguments);
        }
        if (arguments[0] == "enigma") {
            return enigmaCommand(arguments);
        }
    } catch (const UsageError &error) {
        std::cerr << "rlcore: " << error.what() << '\n';
        return 2;
    } catch (const std::runtime_error &error) {
        std::cerr << "rlcore: " << error.what() << '\n';
        return 1;
    }

    std::cerr << "rlcore: unknown command '" << arguments[0] << "'\n";
    printUsage(std::cerr);
    return 2;
}
