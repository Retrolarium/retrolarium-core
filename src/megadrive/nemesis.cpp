#include <retrolarium/core/megadrive/nemesis.hpp>

#include <array>

namespace retrolarium::core {
namespace {

struct CodeEntry final {
    bool valid = false;
    int codeLength = 0;
    int nybble = 0;
    int runLength = 0;
};

// Mirrors the reader in the Python oracle: a 24-bit window refilled a byte at a
// time, reading zeroes once the stream runs out.
class BitReader final {
public:
    BitReader(const std::vector<std::uint8_t> &data, std::size_t position)
        : data_(data)
        , position_(position)
    {
        buffer_ = static_cast<std::uint32_t>(at(position_)) << 8;
        buffer_ |= at(position_ + 1);
        position_ += 2;
        available_ = 16;
    }

    [[nodiscard]] int peek(int count)
    {
        while (available_ < count) {
            refill();
        }
        const int shift = available_ - count;
        return static_cast<int>((buffer_ >> shift) & ((1u << count) - 1u));
    }

    void consume(int count) { available_ -= count; }

private:
    [[nodiscard]] std::uint8_t at(std::size_t index) const
    {
        return index < data_.size() ? data_[index] : std::uint8_t {0};
    }

    void refill()
    {
        // Past the end the oracle shifts in nothing rather than failing, so a
        // truncated stream decodes the same way on both sides.
        const std::uint32_t next = position_ < data_.size() ? data_[position_] : 0u;
        if (position_ < data_.size()) {
            ++position_;
        }
        buffer_ = ((buffer_ << 8) | next) & 0xFFFFFFu;
        available_ += 8;
    }

    const std::vector<std::uint8_t> &data_;
    std::size_t position_ = 0;
    std::uint32_t buffer_ = 0;
    int available_ = 0;
};

} // namespace

std::vector<std::uint8_t> nemesisDecompress(const std::vector<std::uint8_t> &data)
{
    const auto require = [&data](std::size_t index) {
        if (index >= data.size()) {
            throw NemesisError("Nemesis stream ended inside its header");
        }
        return data[index];
    };

    std::size_t position = 0;
    const int header = (require(0) << 8) | require(1);
    position = 2;

    const bool xorMode = (header & 0x8000) != 0;
    int outputCount = (header & 0x7FFF) * 8;
    if (outputCount == 0) {
        return {};
    }

    std::array<CodeEntry, 256> codeTable {};

    while (true) {
        int value = require(position++);
        if (value == 0xFF) {
            break;
        }
        int paletteIndex = value & 0x0F;

        while (true) {
            value = require(position++);
            if (value >= 0x80) {
                if (value == 0xFF) {
                    break;
                }
                paletteIndex = value & 0x0F;
                continue;
            }

            const int runLength = ((value >> 4) & 7) + 1;
            int codeLength = value & 0x0F;
            if (codeLength == 0) {
                codeLength = 8;
            }
            const int codeByte = require(position++);

            if (codeLength < 8) {
                const int base = codeByte << (8 - codeLength);
                const int entries = 1 << (8 - codeLength);
                for (int index = 0; index < entries; ++index) {
                    codeTable[static_cast<std::size_t>(base | index)] =
                        {true, codeLength, paletteIndex, runLength};
                }
            } else {
                codeTable[static_cast<std::size_t>(codeByte)] =
                    {true, codeLength, paletteIndex, runLength};
            }
        }
        if (value == 0xFF) {
            break;
        }
    }

    BitReader reader(data, position);

    std::vector<std::uint8_t> output;
    output.reserve(static_cast<std::size_t>(outputCount) * 4);
    std::uint32_t nybbleBuffer = 0;
    int nybblesBuffered = 0;
    std::uint32_t xorBuffer = 0;

    // Returns true once the declared tile count has been produced.
    const auto outputNybble = [&](int nybble) {
        nybbleBuffer = (nybbleBuffer << 4) | static_cast<std::uint32_t>(nybble & 0xF);
        ++nybblesBuffered;
        if (nybblesBuffered != 8) {
            return false;
        }

        std::uint32_t word = nybbleBuffer;
        if (xorMode) {
            word ^= xorBuffer;
            xorBuffer = word;
        }
        output.push_back(static_cast<std::uint8_t>((word >> 24) & 0xFF));
        output.push_back(static_cast<std::uint8_t>((word >> 16) & 0xFF));
        output.push_back(static_cast<std::uint8_t>((word >> 8) & 0xFF));
        output.push_back(static_cast<std::uint8_t>(word & 0xFF));

        nybbleBuffer = 0;
        nybblesBuffered = 0;
        --outputCount;
        return outputCount == 0;
    };

    while (outputCount > 0) {
        const int lookup = reader.peek(8);
        const CodeEntry &entry = codeTable[static_cast<std::size_t>(lookup)];
        if (entry.valid) {
            reader.consume(entry.codeLength);
            for (int repeat = 0; repeat < entry.runLength; ++repeat) {
                if (outputNybble(entry.nybble)) {
                    return output;
                }
            }
        } else if ((lookup >> 2) == 0x3F) {
            // Inline run: six-bit escape, then a three-bit length and a nybble.
            reader.consume(6);
            const int runLength = reader.peek(3) + 1;
            reader.consume(3);
            const int nybble = reader.peek(4);
            reader.consume(4);
            for (int repeat = 0; repeat < runLength; ++repeat) {
                if (outputNybble(nybble)) {
                    return output;
                }
            }
        } else {
            reader.consume(1);
        }
    }

    return output;
}

} // namespace retrolarium::core
