#include <retrolarium/core/megadrive/enigma.hpp>

namespace retrolarium::core {
namespace {

// Same 24-bit window the Nemesis reader uses, and the same behaviour past the
// end of the stream: shift in zeroes rather than fail.
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

    [[nodiscard]] int read(int count)
    {
        const int value = peek(count);
        available_ -= count;
        return value;
    }

    [[nodiscard]] int peek(int count)
    {
        while (available_ < count) {
            refill();
        }
        return static_cast<int>(
            (buffer_ >> (available_ - count)) & ((1u << count) - 1u));
    }

    void giveBack(int count) { available_ += count; }

private:
    [[nodiscard]] std::uint8_t at(std::size_t index) const
    {
        return index < data_.size() ? data_[index] : std::uint8_t {0};
    }

    void refill()
    {
        // A stream that runs on well past its end never reaches its
        // terminator: refused, not decoded for ever.
        const std::uint32_t next = position_ < data_.size() ? data_[position_] : 0u;
        if (position_ < data_.size()) {
            ++position_;
        } else if (++pastEnd_ > kPastEndBytes) {
            throw EnigmaError("Enigma stream ended before its terminator");
        }
        buffer_ = ((buffer_ << 8) | next) & 0xFFFFFFu;
        available_ += 8;
    }

    static constexpr int kPastEndBytes = 4;
    int pastEnd_ = 0;

    const std::vector<std::uint8_t> &data_;
    std::size_t position_ = 0;
    std::uint32_t buffer_ = 0;
    int available_ = 0;
};

constexpr std::size_t kMaxOutput = 0x10000;

void emit(std::vector<std::uint8_t> &output, int tile)
{
    output.push_back(static_cast<std::uint8_t>((tile >> 8) & 0xFF));
    output.push_back(static_cast<std::uint8_t>(tile & 0xFF));
}

} // namespace

std::vector<std::uint8_t> enigmaDecompress(
    const std::vector<std::uint8_t> &data, int baseTile)
{
    const auto require = [&data](std::size_t index) {
        if (index >= data.size()) {
            throw EnigmaError("Enigma stream ended inside its header");
        }
        return static_cast<int>(data[index]);
    };

    // The header's first two bytes are read as signed bytes by the engine.
    int bitsCount = require(0);
    if (bitsCount >= 0x80) {
        bitsCount -= 0x100;
    }
    // Tile words are 16 bits: a wider field is not a tile map (and would
    // shift past the reader's mask).
    if (bitsCount > 16 || bitsCount < -16) {
        throw EnigmaError("Enigma tile field is wider than 16 bits");
    }
    int flagsByte = require(1);
    if (flagsByte >= 0x80) {
        flagsByte -= 0x100;
    }

    // The engine derives the flag mask with ror.l #1 followed by ror.w #1, so
    // the vertical-flip bit ends up in bit 31 and the horizontal one in bit 15.
    std::uint32_t flags = static_cast<std::uint32_t>(flagsByte);
    flags = (flags >> 1) | ((flags & 1u) << 31);
    std::uint32_t low = flags & 0xFFFFu;
    low = ((low >> 1) | ((low & 1u) << 15)) & 0xFFFFu;
    flags = (flags & 0xFFFF0000u) | low;

    int incTile = ((require(2) << 8) | require(3)) + baseTile;
    int staticTile = ((require(4) << 8) | require(5)) + baseTile;

    BitReader reader(data, 6);

    const auto decodeTile = [&]() {
        int tile = baseTile;
        if ((flags & 0x80000000u) != 0 && reader.read(1) != 0) {
            tile |= 0x1000;
        }
        if ((flags & 0x8000u) != 0 && reader.read(1) != 0) {
            tile |= 0x0800;
        }
        int bits = bitsCount;
        if (bits == 0) {
            return tile;
        }
        if (bits < 0) {
            bits = -bits;
        }
        return tile + reader.read(bits);
    };

    std::vector<std::uint8_t> output;

    while (true) {
        // A plane fills 64 KB of video memory at most.
        if (output.size() > kMaxOutput) {
            throw EnigmaError("Enigma stream decodes past 64 KB without its terminator");
        }
        // Codes are seven bits, except that a leading zero marks a six-bit one;
        // the engine reads seven and hands the spare bit back.
        int code = reader.read(7);
        if (code < 0x40) {
            code >>= 1;
            reader.giveBack(1);
        }

        const int mode = (code >> 4) & 0x07;
        const int repeat = code & 0x0F;

        switch (mode) {
        case 0:
        case 1:
            for (int index = 0; index <= repeat; ++index) {
                emit(output, incTile);
                incTile = (incTile + 1) & 0xFFFF;
            }
            break;
        case 2:
        case 3:
            for (int index = 0; index <= repeat; ++index) {
                emit(output, staticTile);
            }
            break;
        case 4: {
            const int tile = decodeTile();
            for (int index = 0; index <= repeat; ++index) {
                emit(output, tile);
            }
            break;
        }
        case 5: {
            int tile = decodeTile();
            for (int index = 0; index <= repeat; ++index) {
                emit(output, tile);
                tile = (tile + 1) & 0xFFFF;
            }
            break;
        }
        case 6: {
            int tile = decodeTile();
            for (int index = 0; index <= repeat; ++index) {
                emit(output, tile);
                tile = (tile - 1) & 0xFFFF;
            }
            break;
        }
        default:
            if (repeat == 0x0F) {
                return output;
            }
            for (int index = 0; index <= repeat; ++index) {
                emit(output, decodeTile());
            }
            break;
        }
    }
}

} // namespace retrolarium::core
