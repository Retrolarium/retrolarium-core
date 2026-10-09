// Cross-language parity for the PPU display-list grammar.
//
// The corpus comes from tools/generate-nes-ppu-packets-golden.py,
// which drives retrolarium_kit.platform.nes.screen_packets.

#include <retrolarium/core/nes/ppu_packets.hpp>

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

std::vector<int> parseCsv(const std::string &text)
{
    std::vector<int> values;
    std::istringstream stream(text);
    std::string item;
    while (std::getline(stream, item, ',')) {
        if (!item.empty()) {
            values.push_back(std::stoi(item));
        }
    }
    return values;
}

// "8192:0:0:4:1,2,3,4;8256:1:1:5:3"
std::vector<retrolarium::core::NesPpuCommand> parseCommands(const std::string &text)
{
    std::vector<retrolarium::core::NesPpuCommand> commands;
    std::istringstream outer(text);
    std::string entry;
    while (std::getline(outer, entry, ';')) {
        if (entry.empty()) continue;
        std::istringstream inner(entry);
        std::string field;
        std::vector<std::string> fields;
        while (std::getline(inner, field, ':')) {
            fields.push_back(field);
        }
        if (fields.size() < 4) continue;
        retrolarium::core::NesPpuCommand command;
        command.address = std::stoi(fields[0]);
        command.vertical = fields[1] == "1";
        command.repeat = fields[2] == "1";
        command.length = std::stoi(fields[3]);
        command.values = fields.size() > 4 ? parseCsv(fields[4]) : std::vector<int> {};
        commands.push_back(std::move(command));
    }
    return commands;
}

} // namespace

int main(int argc, char *argv[])
{
    if (argc != 2) {
        std::cerr
            << "usage: retrolarium-core-nes-ppu-packets-golden-tests <corpus.txt>\n";
        return 2;
    }

    std::ifstream stream(argv[1]);
    if (!stream) {
        std::cerr << "cannot open corpus " << argv[1] << '\n';
        return 2;
    }

    int terminator = 0;
    std::string name;
    bool rejecting = false;
    std::vector<std::uint8_t> payload;
    std::vector<retrolarium::core::NesPpuCommand> wantedCommands;
    std::vector<int> wantedTrailing;
    int cases = 0;
    int rejections = 0;
    std::string line;
    bool firstLine = true;

    const auto rest = [](std::istringstream &fields) {
        std::string value;
        std::getline(fields, value);
        if (!value.empty() && value.front() == ' ') value.erase(0, 1);
        return value;
    };

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
            if (value != "retrolarium.nes-ppu-packets-golden") {
                report("unexpected corpus schema " + value);
            }
        } else if (key == "schema_version" || key == "generator") {
            continue;
        } else if (key == "terminator") {
            fields >> terminator;
        } else if (key == "case" || key == "reject-case") {
            rejecting = key == "reject-case";
            fields >> name;
            payload.clear();
            wantedCommands.clear();
            wantedTrailing.clear();
        } else if (key == "payload") {
            std::string value;
            fields >> value;
            payload = fromHex(value);
        } else if (key == "commands") {
            wantedCommands = parseCommands(rest(fields));
        } else if (key == "trailing") {
            wantedTrailing = parseCsv(rest(fields));
        } else if (key == "end") {
            if (rejecting) {
                ++rejections;
                try {
                    static_cast<void>(retrolarium::core::decodePpuCommands(
                        payload, terminator, name));
                    report(name + " was accepted but both sides must refuse it");
                } catch (const retrolarium::core::NesPpuPacketError &) {
                }
                continue;
            }

            ++cases;
            try {
                const auto packet = retrolarium::core::decodePpuCommands(
                    payload, terminator, name);
                if (packet.commands != wantedCommands) {
                    report(name + " commands differ from the oracle");
                }
                if (packet.trailing != wantedTrailing) {
                    report(name + " trailing bytes differ from the oracle");
                }
                // Re-emitting has to reproduce the payload exactly, padding
                // included, or the packet would not fit its fixed capacity.
                const auto rebuilt = retrolarium::core::encodePpuCommands(
                    packet, terminator, payload.size(), name);
                if (rebuilt != payload) {
                    report(name + " does not round-trip");
                }
            } catch (const retrolarium::core::NesPpuPacketError &error) {
                report(name + " raised: " + error.what());
            }
        } else {
            report("unknown corpus key \"" + key + "\"");
        }
    }

    // A packet that no longer fills its capacity must be refused rather than
    // silently padded or truncated.
    try {
        retrolarium::core::NesPpuPacket packet;
        packet.commands.push_back({0x2000, false, false, 1, {1}});
        static_cast<void>(
            retrolarium::core::encodePpuCommands(packet, terminator, 99, "capacity"));
        report("a packet that underfills its capacity was accepted");
    } catch (const retrolarium::core::NesPpuPacketError &) {
    }

    if (cases == 0 || rejections == 0) {
        std::cerr << "corpus was missing cases or rejections\n";
        return 2;
    }
    if (failures != 0) {
        std::cerr << failures << " PPU packet parity check(s) failed\n";
        return 1;
    }
    std::cout << "PPU packet parity: " << cases << " cases, " << rejections
              << " rejections\n";
    return 0;
}
