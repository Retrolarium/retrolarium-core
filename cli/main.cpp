// rlcore: the command-line face of retrolarium_core.
//
// The same library is linked straight into the Qt application, so this file
// stays a thin argument parser. Anything with real logic belongs in the
// library, where both consumers and the tests reach it.

#include <retrolarium/core/megadrive/enigma.hpp>
#include <retrolarium/core/megadrive/nemesis.hpp>
#include <retrolarium/core/version.hpp>

#include <cerrno>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <exception>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#ifdef _WIN32
#include <windows.h>
#include <shellapi.h>
#else
#include <fcntl.h>
#include <unistd.h>
#endif

namespace {

// Exit codes: 1 a codec refused its data, 2 the command line is wrong, 3 a
// file could not be read or written.
class UsageError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

class IoError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// What the C library said about the last failed call, for an IoError.
std::string reason() {
    const int code = errno;
    return code != 0 ? std::string(": ") + std::strerror(code) : std::string();
}

void printUsage(std::ostream& out) {
    out << "usage: rlcore <command> [arguments]\n"
           "\n"
           "commands:\n"
           "  nemesis decompress <in.nem> <out.bin>\n"
           "  nemesis compress <plain.bin> <reference.nem> <out.nem>\n"
           "      re-encode using the reference's own code table\n"
           "  enigma decompress <in.eni> <out.bin> [base-tile]\n"
           "  enigma compress <plain.bin> <out.eni>\n"
           "  version\n"
           "\n"
           "exit status: 1 the data was refused, 2 a usage error, 3 a file could not be read or written\n";
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

unsigned long processId() { return static_cast<unsigned long>(GetCurrentProcessId()); }

// MoveFileExW with MOVEFILE_WRITE_THROUGH already flushes the move.
bool flushFile(std::FILE* file) { return std::fflush(file) == 0; }

void flushFolder(const std::string&) {}
#else
std::FILE* openFile(const std::string& path, const char* mode) { return std::fopen(path.c_str(), mode); }

bool replaceFile(const std::string& from, const std::string& to) { return std::rename(from.c_str(), to.c_str()) == 0; }

void removeFile(const std::string& path) { std::remove(path.c_str()); }

unsigned long processId() { return static_cast<unsigned long>(getpid()); }

// The data reaches the disk before the rename makes it the file.
bool flushFile(std::FILE* file) { return std::fflush(file) == 0 && fsync(fileno(file)) == 0; }

// And the rename itself, recorded in the folder. A folder that cannot be
// opened or synced (some file systems refuse) leaves the file written anyway.
void flushFolder(const std::string& path) {
    const std::size_t slash = path.find_last_of('/');
    const std::string folder = slash == std::string::npos ? std::string(".") : path.substr(0, slash + 1);
    const int descriptor = open(folder.c_str(), O_RDONLY);
    if (descriptor >= 0) {
        (void)fsync(descriptor);
        close(descriptor);
    }
}
#endif

#ifdef _WIN32
#define RL_MODE(text) L##text
#else
#define RL_MODE(text) text
#endif

std::vector<std::uint8_t> readFile(const std::string& path) {
    errno = 0;
    std::FILE* file = openFile(path, RL_MODE("rb"));
    if (file == nullptr) {
        throw IoError("cannot read " + path + reason());
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
        throw IoError("failed while reading " + path);
    }
    return data;
}

// A name beside the file that no other rlcore (or an earlier one that died
// half way) is writing: the process and a clock reading.
std::string temporaryName(const std::string& path) {
    const auto ticks = std::chrono::high_resolution_clock::now().time_since_epoch().count();
    return path + ".rlcore-" + std::to_string(processId()) + "-" +
           std::to_string(static_cast<unsigned long long>(ticks)) + ".tmp";
}

// Written beside the file, then moved over it: a failed write (a full disk)
// leaves the file as it was.
void writeFile(const std::string& path, const std::vector<std::uint8_t>& data) {
    const std::string temporary = temporaryName(path);
    errno = 0;
    std::FILE* file = openFile(temporary, RL_MODE("wb"));
    if (file == nullptr) {
        throw IoError("cannot write " + path + reason());
    }
    const bool written = std::fwrite(data.data(), 1, data.size(), file) == data.size() && flushFile(file);
    const bool closed = std::fclose(file) == 0;
    if (!written || !closed) {
        removeFile(temporary);
        throw IoError("failed while writing " + path);
    }
    if (!replaceFile(temporary, path)) {
        removeFile(temporary);
        throw IoError("cannot replace " + path);
    }
    flushFolder(path);
}

// The length of the well-formed UTF-8 sequence at value[index] (two to four
// bytes), or 0 when the bytes there are not one.
std::size_t utf8Length(const std::string& value, std::size_t index) {
    const auto byteAt = [&value](std::size_t at) { return static_cast<unsigned char>(value[at]); };
    const unsigned char lead = byteAt(index);
    std::size_t length = 0;
    std::uint32_t code = 0;
    std::uint32_t minimum = 0;
    if (lead >= 0xC2 && lead <= 0xDF) {
        length = 2;
        code = lead & 0x1Fu;
        minimum = 0x80;
    } else if (lead >= 0xE0 && lead <= 0xEF) {
        length = 3;
        code = lead & 0x0Fu;
        minimum = 0x800;
    } else if (lead >= 0xF0 && lead <= 0xF4) {
        length = 4;
        code = lead & 0x07u;
        minimum = 0x10000;
    } else {
        return 0;
    }
    if (index + length > value.size()) {
        return 0;
    }
    for (std::size_t offset = 1; offset < length; ++offset) {
        const unsigned char next = byteAt(index + offset);
        if ((next & 0xC0u) != 0x80u) {
            return 0;
        }
        code = (code << 6) | (next & 0x3Fu);
    }
    if (code < minimum || code > 0x10FFFF || (code >= 0xD800 && code <= 0xDFFF)) {
        return 0;
    }
    return length;
}

std::string jsonEscape(const std::string& value) {
    std::string out;
    out.reserve(value.size() + 2);
    std::size_t index = 0;
    while (index < value.size()) {
        const char character = value[index];
        if (static_cast<unsigned char>(character) >= 0x80) {
            // A path that is not UTF-8 (a legacy code page) still makes valid
            // JSON: each stray byte becomes U+FFFD.
            const std::size_t length = utf8Length(value, index);
            if (length == 0) {
                out += "\\ufffd";
                ++index;
            } else {
                out.append(value, index, length);
                index += length;
            }
            continue;
        }
        ++index;
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

// A tile word from 0 to 0xFFFF, in decimal or 0x-prefixed hexadecimal. A
// sign, a space, a trailing letter or a larger value is refused, so the
// decoder never adds a base that overflows its tile arithmetic.
int parseBaseTile(const std::string& text) {
    const char* const message = "base-tile must be a whole number from 0 to 0xFFFF (65535)";
    std::size_t index = 0;
    int base = 10;
    if (text.size() > 2 && text[0] == '0' && (text[1] == 'x' || text[1] == 'X')) {
        index = 2;
        base = 16;
    }
    if (index == text.size()) {
        throw UsageError(message);
    }
    long value = 0;
    for (; index < text.size(); ++index) {
        const char character = text[index];
        int digit = -1;
        if (character >= '0' && character <= '9') {
            digit = character - '0';
        } else if (base == 16 && character >= 'a' && character <= 'f') {
            digit = character - 'a' + 10;
        } else if (base == 16 && character >= 'A' && character <= 'F') {
            digit = character - 'A' + 10;
        }
        if (digit < 0) {
            throw UsageError(message);
        }
        value = value * base + digit;
        if (value > 0xFFFF) {
            throw UsageError(message);
        }
    }
    return static_cast<int>(value);
}

int enigmaCommand(const std::vector<std::string>& arguments) {
    if ((arguments.size() == 4 || arguments.size() == 5) && arguments[1] == "decompress") {
        const int baseTile = arguments.size() == 5 ? parseBaseTile(arguments[4]) : 0;
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

}  // namespace

int main(int argc, char* argv[]) {
    const std::vector<std::string> arguments = utf8Arguments(argc, argv);
    if (arguments.empty() || arguments[0] == "-h" || arguments[0] == "--help") {
        printUsage(arguments.empty() ? std::cerr : std::cout);
        return arguments.empty() ? 2 : 0;
    }

    try {
        if (arguments[0] == "version") {
            std::cout << retrolarium::core::kVersion << '\n';
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
    } catch (const IoError& error) {
        std::cerr << "rlcore: " << error.what() << '\n';
        return 3;
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
