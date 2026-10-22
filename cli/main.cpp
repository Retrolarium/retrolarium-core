// rlcore: the command-line face of retrolarium_core.
//
// The same library is linked straight into the Qt application, so this file
// stays a thin argument parser. Anything with real logic belongs in the
// library, where both consumers and the tests reach it.

#include <retrolarium/core/megadrive/enigma.hpp>
#include <retrolarium/core/megadrive/nemesis.hpp>

#include <cstdint>
#include <cstdio>
#include <exception>
#include <iostream>
#include <string>
#include <vector>

#ifdef _WIN32
#include <windows.h>
#include <shellapi.h>
#endif

namespace {

constexpr char kVersion[] = "0.1.0";

class UsageError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

void printUsage(std::ostream& out) {
    out << "usage: rlcore <command> [arguments]\n"
           "\n"
           "commands:\n"
           "  nemesis decompress <in.nem> <out.bin>\n"
           "  nemesis compress <plain.bin> <reference.nem> <out.nem>\n"
           "      re-encode using the reference's own code table\n"
           "  enigma decompress <in.eni> <out.bin> [base-tile]\n"
           "  enigma compress <plain.bin> <out.eni>\n"
           "  version\n";
}

// Arguments arrive as UTF-8 (see main). On Windows a path is opened as
// UTF-16, so a folder named outside the system's code page still opens; the
// C library stands in for std::filesystem, which the cross-build's GCC 7.3
// does not have.
#ifdef _WIN32
std::wstring widePath(const std::string& utf8) {
    const int size = MultiByteToWideChar(CP_UTF8, 0, utf8.c_str(), -1, nullptr, 0);
    std::wstring wide(size > 0 ? static_cast<std::size_t>(size - 1) : 0, L'\0');
    if (size > 1) {
        MultiByteToWideChar(CP_UTF8, 0, utf8.c_str(), -1, &wide[0], size);
    }
    return wide;
}

std::FILE* openFile(const std::string& path, const wchar_t* mode) { return _wfopen(widePath(path).c_str(), mode); }

bool replaceFile(const std::string& from, const std::string& to) {
    return MoveFileExW(widePath(from).c_str(), widePath(to).c_str(),
                       MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) != 0;
}

void removeFile(const std::string& path) { _wremove(widePath(path).c_str()); }
#else
std::FILE* openFile(const std::string& path, const char* mode) { return std::fopen(path.c_str(), mode); }

bool replaceFile(const std::string& from, const std::string& to) { return std::rename(from.c_str(), to.c_str()) == 0; }

void removeFile(const std::string& path) { std::remove(path.c_str()); }
#endif

#ifdef _WIN32
#define RL_MODE(text) L##text
#else
#define RL_MODE(text) text
#endif

std::vector<std::uint8_t> readFile(const std::string& path) {
    std::FILE* file = openFile(path, RL_MODE("rb"));
    if (file == nullptr) {
        throw UsageError("cannot read " + path);
    }
    std::vector<std::uint8_t> data;
    std::uint8_t block[65536];
    std::size_t count = 0;
    while ((count = std::fread(block, 1, sizeof block, file)) > 0) {
        data.insert(data.end(), block, block + count);
    }
    const bool failed = std::ferror(file) != 0;
    std::fclose(file);
    if (failed) {
        throw UsageError("failed while reading " + path);
    }
    return data;
}

// Written beside the file, then moved over it: a failed write (a full disk)
// leaves the file as it was.
void writeFile(const std::string& path, const std::vector<std::uint8_t>& data) {
    const std::string temporary = path + ".rlcore-tmp";
    std::FILE* file = openFile(temporary, RL_MODE("wb"));
    if (file == nullptr) {
        throw UsageError("cannot write " + path);
    }
    const bool written = std::fwrite(data.data(), 1, data.size(), file) == data.size();
    const bool closed = std::fclose(file) == 0;
    if (!written || !closed) {
        removeFile(temporary);
        throw UsageError("failed while writing " + path);
    }
    if (!replaceFile(temporary, path)) {
        removeFile(temporary);
        throw UsageError("cannot replace " + path);
    }
}

std::string jsonEscape(const std::string& value) {
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
                if (static_cast<unsigned char>(character) < 0x20) {
                    char escaped[8];
                    std::snprintf(escaped, sizeof escaped, "\\u%04x", static_cast<unsigned char>(character));
                    out += escaped;
                } else {
                    out.push_back(character);
                }
        }
    }
    return out;
}

// Reports what was written so a caller can log or check it without re-reading
// the file.
void reportWritten(const std::string& path, std::size_t bytes) {
    std::cout << "{\"schema\": \"retrolarium.codec-result\", \"schema_version\": 1, "
              << "\"output\": \"" << jsonEscape(path) << "\", \"size\": " << bytes << "}\n";
}

int nemesisCommand(const std::vector<std::string>& arguments) {
    if (arguments.size() == 4 && arguments[1] == "decompress") {
        const auto out = retrolarium::core::nemesisDecompress(readFile(arguments[2]));
        writeFile(arguments[3], out);
        reportWritten(arguments[3], out.size());
        return 0;
    }
    if (arguments.size() == 5 && arguments[1] == "compress") {
        const auto out = retrolarium::core::nemesisCompress(readFile(arguments[2]), readFile(arguments[3]));
        writeFile(arguments[4], out);
        reportWritten(arguments[4], out.size());
        return 0;
    }
    throw UsageError(
        "nemesis takes 'decompress <in> <out>' or "
        "'compress <plain> <reference> <out>'");
}

int enigmaCommand(const std::vector<std::string>& arguments) {
    if ((arguments.size() == 4 || arguments.size() == 5) && arguments[1] == "decompress") {
        int baseTile = 0;
        if (arguments.size() == 5) {
            try {
                baseTile = std::stoi(arguments[4], nullptr, 0);
            } catch (const std::exception&) {
                throw UsageError("base-tile must be an integer");
            }
        }
        const auto out = retrolarium::core::enigmaDecompress(readFile(arguments[2]), baseTile);
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
    throw UsageError(
        "enigma takes 'decompress <in> <out> [base-tile]' or "
        "'compress <plain> <out>'");
}

}  // namespace

// The arguments as UTF-8: on Windows argv is in the system's code page, which
// loses any character outside it, so the wide command line is read instead.
std::vector<std::string> utf8Arguments(int argc, char* argv[]) {
#ifdef _WIN32
    int count = 0;
    wchar_t** wide = CommandLineToArgvW(GetCommandLineW(), &count);
    if (wide != nullptr) {
        std::vector<std::string> result;
        for (int index = 1; index < count; ++index) {
            const int size = WideCharToMultiByte(CP_UTF8, 0, wide[index], -1, nullptr, 0, nullptr, nullptr);
            std::string text(size > 0 ? static_cast<std::size_t>(size - 1) : 0, '\0');
            if (size > 1) {
                WideCharToMultiByte(CP_UTF8, 0, wide[index], -1, text.data(), size, nullptr, nullptr);
            }
            result.push_back(text);
        }
        LocalFree(wide);
        return result;
    }
#endif
    return {argv + 1, argv + argc};
}

int main(int argc, char* argv[]) {
    const std::vector<std::string> arguments = utf8Arguments(argc, argv);
    if (arguments.empty() || arguments[0] == "-h" || arguments[0] == "--help") {
        printUsage(arguments.empty() ? std::cerr : std::cout);
        return arguments.empty() ? 2 : 0;
    }

    try {
        if (arguments[0] == "version") {
            std::cout << kVersion << '\n';
            return 0;
        }
        if (arguments[0] == "nemesis") {
            return nemesisCommand(arguments);
        }
        if (arguments[0] == "enigma") {
            return enigmaCommand(arguments);
        }
    } catch (const UsageError& error) {
        std::cerr << "rlcore: " << error.what() << '\n';
        return 2;
    } catch (const std::runtime_error& error) {
        std::cerr << "rlcore: " << error.what() << '\n';
        return 1;
    } catch (const std::exception& error) {
        // Out of memory and the like: still one line and a failure, not an abort.
        std::cerr << "rlcore: " << error.what() << '\n';
        return 1;
    }

    std::cerr << "rlcore: unknown command '" << arguments[0] << "'\n";
    printUsage(std::cerr);
    return 2;
}
