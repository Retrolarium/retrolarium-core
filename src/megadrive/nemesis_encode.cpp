#include <retrolarium/core/megadrive/nemesis.hpp>

#include <map>
#include <string>
#include <utility>

namespace retrolarium::core {
namespace {

struct ReferenceHeader final {
    bool xorMode = false;
    // (nybble, run) -> (code value, code bit length)
    std::map<std::pair<int, int>, std::pair<int, int>> codes;
    std::size_t headerSize = 0;
};

ReferenceHeader parseReference(const std::vector<std::uint8_t>& reference) {
    const auto require = [&reference](std::size_t index) {
        if (index >= reference.size()) {
            throw NemesisError("Nemesis reference ended inside its code table");
        }
        return static_cast<int>(reference[index]);
    };

    ReferenceHeader result;
    result.xorMode = ((require(0) << 8) | require(1)) & 0x8000;

    std::size_t position = 2;
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
            // First definition wins, matching the oracle's setdefault.
            result.codes.emplace(std::make_pair(paletteIndex, runLength), std::make_pair(codeByte, codeLength));
        }
        if (value == 0xFF) {
            break;
        }
    }
    result.headerSize = position;
    return result;
}

// Flattens tile data into nybbles, undoing the XOR chaining the stream applies
// on the way out.
std::vector<int> toNybbles(const std::vector<std::uint8_t>& plain, bool xorMode) {
    std::vector<int> nybbles;
    nybbles.reserve(plain.size() * 2);
    std::uint32_t previous = 0;
    for (std::size_t offset = 0; offset + 3 < plain.size(); offset += 4) {
        const std::uint32_t word = (static_cast<std::uint32_t>(plain[offset]) << 24) |
                                   (static_cast<std::uint32_t>(plain[offset + 1]) << 16) |
                                   (static_cast<std::uint32_t>(plain[offset + 2]) << 8) | plain[offset + 3];
        std::uint32_t stored = word;
        if (xorMode) {
            stored = word ^ previous;
            previous = word;
        }
        for (int shift = 28; shift >= 0; shift -= 4) {
            nybbles.push_back(static_cast<int>((stored >> shift) & 0xF));
        }
    }
    return nybbles;
}

class BitWriter final {
public:
    void write(int value, int count) {
        for (int shift = count - 1; shift >= 0; --shift) {
            bits_.push_back((value >> shift) & 1);
        }
    }

    [[nodiscard]] std::vector<std::uint8_t> toBytes(int pad) const {
        std::vector<std::uint8_t> out;
        for (std::size_t index = 0; index < bits_.size(); index += 8) {
            int value = 0;
            for (std::size_t offset = 0; offset < 8; ++offset) {
                value = (value << 1) | (index + offset < bits_.size() ? bits_[index + offset] : pad);
            }
            out.push_back(static_cast<std::uint8_t>(value));
        }
        return out;
    }

private:
    std::vector<int> bits_;
};

}  // namespace

std::vector<std::uint8_t> nemesisCompress(const std::vector<std::uint8_t>& plain,
                                          const std::vector<std::uint8_t>& reference) {
    const ReferenceHeader header = parseReference(reference);
    // The reference's header (tile count included) is copied: the data must
    // be that many tiles, or the stream would decode to something else.
    const std::size_t tiles = static_cast<std::size_t>(((reference[0] << 8) | reference[1]) & 0x7FFF);
    if (plain.size() != tiles * 32) {
        throw NemesisError("Nemesis data is " + std::to_string(plain.size()) + " bytes; the reference holds " +
                           std::to_string(tiles) + " tiles of 32");
    }
    const std::vector<int> nybbles = toNybbles(plain, header.xorMode);
    const std::size_t total = nybbles.size();

    struct Choice final {
        int run = 0;
        bool inlineRun = true;
        int nybble = 0;
    };

    std::vector<int> costs(total + 1, 0);
    std::vector<Choice> choices(total);

    for (std::size_t reverse = total; reverse > 0; --reverse) {
        const std::size_t index = reverse - 1;
        const int nybble = nybbles[index];
        std::size_t maximum = 1;
        while (maximum < 8 && index + maximum < total && nybbles[index + maximum] == nybble) {
            ++maximum;
        }

        bool haveBest = false;
        int bestCost = 0;
        int bestRun = 0;
        Choice bestChoice;
        // The oracle takes min over (cost, -run, choice); a table code is
        // always shorter than the thirteen-bit inline form, so the third
        // element never has to break a tie.
        const auto consider = [&](int cost, int run, Choice choice) {
            if (haveBest && (cost > bestCost || (cost == bestCost && run <= bestRun))) {
                return;
            }
            bestCost = cost;
            bestRun = run;
            bestChoice = choice;
            haveBest = true;
        };

        for (std::size_t run = 1; run <= maximum; ++run) {
            const int tail = costs[index + run];
            const auto found = header.codes.find(std::make_pair(nybble, static_cast<int>(run)));
            if (found != header.codes.end()) {
                consider(found->second.second + tail, static_cast<int>(run),
                         Choice{static_cast<int>(run), false, nybble});
            }
            consider(13 + tail, static_cast<int>(run), Choice{static_cast<int>(run), true, nybble});
        }

        costs[index] = bestCost;
        choices[index] = bestChoice;
    }

    BitWriter writer;
    std::size_t index = 0;
    while (index < total) {
        const Choice& choice = choices[index];
        if (choice.inlineRun) {
            writer.write(0x3F, 6);
            writer.write(choice.run - 1, 3);
            writer.write(choice.nybble, 4);
        } else {
            const auto found = header.codes.find(std::make_pair(choice.nybble, choice.run));
            writer.write(found->second.first, found->second.second);
        }
        index += static_cast<std::size_t>(choice.run);
    }

    // The header and its code table come from the reference verbatim: reusing
    // them is what removes the only genuinely lossy decision in the format.
    std::vector<std::uint8_t> out(reference.begin(),
                                  reference.begin() + static_cast<std::ptrdiff_t>(header.headerSize));
    // The original pads its final byte with set bits.
    const auto payload = writer.toBytes(1);
    out.insert(out.end(), payload.begin(), payload.end());
    return out;
}

}  // namespace retrolarium::core
