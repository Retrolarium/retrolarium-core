#include <retrolarium/core/nes/ppu_packets.hpp>

namespace retrolarium::core {
namespace {

constexpr int kPpuLow = 0x2000;
constexpr int kPpuHigh = 0x3FFF;
constexpr int kLengthMask = 0x3F;
constexpr int kRepeatFlag = 0x40;
constexpr int kVerticalFlag = 0x80;

} // namespace

NesPpuPacket decodePpuCommands(const std::vector<std::uint8_t> &payload,
    int terminator, const std::string &name)
{
    NesPpuPacket packet;
    std::size_t offset = 0;
    while (offset < payload.size()) {
        if (payload[offset] == terminator) {
            packet.trailing.reserve(payload.size() - offset - 1);
            for (std::size_t index = offset + 1; index < payload.size(); ++index) {
                packet.trailing.push_back(payload[index]);
            }
            return packet;
        }
        if (offset + 3 > payload.size()) {
            throw NesPpuPacketError(
                "screen " + name + " has a truncated command header");
        }

        const int address = (payload[offset] << 8) | payload[offset + 1];
        if (address < kPpuLow || address > kPpuHigh) {
            throw NesPpuPacketError(
                "screen " + name + " command address is outside PPU memory");
        }
        const int control = payload[offset + 2];
        const int length = control & kLengthMask;
        if (length == 0) {
            throw NesPpuPacketError("screen " + name + " command has zero length");
        }
        const bool repeat = (control & kRepeatFlag) != 0;
        const std::size_t valueCount =
            repeat ? 1 : static_cast<std::size_t>(length);
        const std::size_t end = offset + 3 + valueCount;
        if (end > payload.size()) {
            throw NesPpuPacketError(
                "screen " + name + " has truncated command values");
        }

        NesPpuCommand command;
        command.address = address;
        command.vertical = (control & kVerticalFlag) != 0;
        command.repeat = repeat;
        command.length = length;
        command.values.reserve(valueCount);
        for (std::size_t index = offset + 3; index < end; ++index) {
            command.values.push_back(payload[index]);
        }
        packet.commands.push_back(std::move(command));
        offset = end;
    }
    throw NesPpuPacketError("screen " + name + " has no terminator");
}

std::vector<std::uint8_t> encodePpuCommands(const NesPpuPacket &packet,
    int terminator, std::size_t capacity, const std::string &name)
{
    std::vector<std::uint8_t> output;
    output.reserve(capacity);

    for (std::size_t index = 0; index < packet.commands.size(); ++index) {
        const NesPpuCommand &command = packet.commands[index];
        const std::string where =
            "screen " + name + ".commands[" + std::to_string(index) + "]";
        if (command.address < kPpuLow || command.address > kPpuHigh) {
            throw NesPpuPacketError(where + ".address is outside PPU memory");
        }
        if (command.length < 1 || command.length > kLengthMask) {
            throw NesPpuPacketError(where + ".length must be in 1..63");
        }
        const std::size_t expected =
            command.repeat ? 1 : static_cast<std::size_t>(command.length);
        if (command.values.size() != expected) {
            throw NesPpuPacketError(where + ".values has the wrong length");
        }

        output.push_back(static_cast<std::uint8_t>((command.address >> 8) & 0xFF));
        output.push_back(static_cast<std::uint8_t>(command.address & 0xFF));
        output.push_back(static_cast<std::uint8_t>(
            (command.vertical ? kVerticalFlag : 0)
            | (command.repeat ? kRepeatFlag : 0) | command.length));
        for (std::size_t value = 0; value < command.values.size(); ++value) {
            const int item = command.values[value];
            if (item < 0 || item > 0xFF) {
                throw NesPpuPacketError(where + ".values[" + std::to_string(value)
                    + "] must be a byte in 0..255");
            }
            output.push_back(static_cast<std::uint8_t>(item));
        }
    }

    output.push_back(static_cast<std::uint8_t>(terminator));
    for (std::size_t index = 0; index < packet.trailing.size(); ++index) {
        const int item = packet.trailing[index];
        if (item < 0 || item > 0xFF) {
            throw NesPpuPacketError("screen " + name + ".trailing["
                + std::to_string(index) + "] must be a byte in 0..255");
        }
        output.push_back(static_cast<std::uint8_t>(item));
    }

    if (output.size() != capacity) {
        throw NesPpuPacketError(
            "screen " + name + " encoded size differs from its capacity");
    }
    return output;
}

} // namespace retrolarium::core
