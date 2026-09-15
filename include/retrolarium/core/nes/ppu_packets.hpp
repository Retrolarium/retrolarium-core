#pragma once

#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace retrolarium::core {

// Raised when a PPU display list is malformed or will not fit its capacity.
class NesPpuPacketError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// One write the PPU performs: a destination, a direction, and either a run of
// distinct bytes or a single byte repeated.
struct NesPpuCommand final {
    int address = 0;
    bool vertical = false;
    bool repeat = false;
    int length = 0;
    std::vector<int> values;

    [[nodiscard]] bool operator==(const NesPpuCommand &other) const noexcept
    {
        return address == other.address && vertical == other.vertical
            && repeat == other.repeat && length == other.length
            && values == other.values;
    }
    [[nodiscard]] bool operator!=(const NesPpuCommand &other) const noexcept
    {
        return !(*this == other);
    }
};

struct NesPpuPacket final {
    std::vector<NesPpuCommand> commands;
    // Bytes after the terminator. They are fixed padding in the ROM and must
    // come back out unchanged, so they are carried rather than discarded.
    std::vector<int> trailing;
};

// Decodes a display list up to its terminator.
[[nodiscard]] NesPpuPacket decodePpuCommands(
    const std::vector<std::uint8_t> &payload, int terminator,
    const std::string &name);

// Re-emits a display list. `capacity` is the fixed room the ROM gives this
// packet: the result must fill it exactly, because a short write would leave
// stale bytes behind and a long one would overrun the next resource.
[[nodiscard]] std::vector<std::uint8_t> encodePpuCommands(const NesPpuPacket &packet,
    int terminator, std::size_t capacity, const std::string &name);

} // namespace retrolarium::core
