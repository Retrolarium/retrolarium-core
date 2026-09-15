#include <retrolarium/core/enigma.hpp>

#include <algorithm>
#include <map>
#include <utility>

namespace retrolarium::core {
namespace {

// One emitted command: its mode, its repeat field, and any tile words written
// inline after it.
struct Command final {
    int mode = 0;
    int repeat = 0;
    std::vector<int> operands;
};

// A memoised decision: the cheapest command to emit at a position, and the
// state it leads to.
struct Decision final {
    int cost = 0;
    Command command;
    std::size_t nextPosition = 0;
    int nextIncTile = 0;
    bool terminal = false;
};

std::vector<int> wordsFromBytes(const std::vector<std::uint8_t> &data)
{
    if (data.size() % 2 != 0) {
        throw EnigmaError("Enigma input tilemap must contain whole big-endian words");
    }
    std::vector<int> words;
    words.reserve(data.size() / 2);
    for (std::size_t index = 0; index < data.size(); index += 2) {
        words.push_back((data[index] << 8) | data[index + 1]);
    }
    return words;
}

int runLength(const std::vector<int> &values, std::size_t position, int step)
{
    int length = 1;
    while (length < 16
        && position + static_cast<std::size_t>(length) < values.size()
        && values[position + static_cast<std::size_t>(length)]
            == ((values[position] + step * length) & 0xFFFF)) {
        ++length;
    }
    return length;
}

class Solver final {
public:
    Solver(const std::vector<int> &values, int bitsCount)
        : values_(values)
        , bitsCount_(bitsCount)
    {
    }

    // std::map rather than a hash map: nodes keep their address, so a
    // reference handed to a caller survives the recursion's own inserts.
    const Decision &solve(std::size_t position, int incTile)
    {
        const std::uint64_t key = (static_cast<std::uint64_t>(position) << 17)
            | static_cast<std::uint64_t>(incTile & 0xFFFF);
        if (const auto found = memo_.find(key); found != memo_.end()) {
            return found->second;
        }

        if (position == values_.size()) {
            Decision terminal;
            terminal.cost = 7;
            terminal.command = Command {7, 15, {}};
            terminal.terminal = true;
            return memo_.emplace(key, std::move(terminal)).first->second;
        }

        Decision best;
        bool haveBest = false;
        // Candidates are considered in the oracle's order and ties keep the
        // first, which is what makes the two encoders agree byte for byte.
        const auto consider = [&](int cost, Command command, std::size_t next,
                                 int nextIncTile) {
            if (haveBest && cost >= best.cost) {
                return;
            }
            best = Decision {cost, std::move(command), next, nextIncTile, false};
            haveBest = true;
        };

        if (values_[position] == incTile) {
            int length = 0;
            while (length < 16
                && position + static_cast<std::size_t>(length) < values_.size()
                && values_[position + static_cast<std::size_t>(length)]
                    == ((incTile + length) & 0xFFFF)) {
                ++length;
            }
            for (int count = 1; count <= length; ++count) {
                const auto next = position + static_cast<std::size_t>(count);
                const int nextInc = (incTile + count) & 0xFFFF;
                consider(6 + solve(next, nextInc).cost, Command {0, count - 1, {}},
                    next, nextInc);
            }
        }

        static constexpr int kModes[3] {4, 5, 6};
        static constexpr int kSteps[3] {0, 1, -1};
        for (int index = 0; index < 3; ++index) {
            const int maximum = runLength(values_, position, kSteps[index]);
            for (int count = 1; count <= maximum; ++count) {
                const auto next = position + static_cast<std::size_t>(count);
                consider(7 + bitsCount_ + solve(next, incTile).cost,
                    Command {kModes[index], count - 1, {values_[position]}},
                    next, incTile);
            }
        }

        const int literalLimit =
            static_cast<int>(std::min<std::size_t>(15, values_.size() - position));
        for (int count = 1; count <= literalLimit; ++count) {
            const auto next = position + static_cast<std::size_t>(count);
            std::vector<int> literal(
                values_.begin() + static_cast<std::ptrdiff_t>(position),
                values_.begin() + static_cast<std::ptrdiff_t>(next));
            consider(7 + count * bitsCount_ + solve(next, incTile).cost,
                Command {7, count - 1, std::move(literal)}, next, incTile);
        }

        return memo_.emplace(key, std::move(best)).first->second;
    }

    void reset() { memo_.clear(); }

private:
    const std::vector<int> &values_;
    int bitsCount_ = 0;
    std::map<std::uint64_t, Decision> memo_;
};

class BitWriter final {
public:
    void write(int value, int count)
    {
        for (int shift = count - 1; shift >= 0; --shift) {
            bits_.push_back((value >> shift) & 1);
        }
    }

    [[nodiscard]] std::vector<std::uint8_t> toBytes() const
    {
        std::vector<std::uint8_t> out;
        for (std::size_t index = 0; index < bits_.size(); index += 8) {
            int value = 0;
            for (std::size_t offset = 0; offset < 8; ++offset) {
                value = (value << 1)
                    | (index + offset < bits_.size() ? bits_[index + offset] : 0);
            }
            out.push_back(static_cast<std::uint8_t>(value));
        }
        return out;
    }

private:
    std::vector<int> bits_;
};

} // namespace

std::vector<std::uint8_t> enigmaCompress(const std::vector<std::uint8_t> &data)
{
    const std::vector<int> values = wordsFromBytes(data);
    if (values.empty()) {
        throw EnigmaError("Enigma cannot encode an empty tilemap");
    }

    // Matches max(1, largest.bit_length()) in the oracle.
    const int largest = *std::max_element(values.begin(), values.end());
    int bitsCount = 1;
    for (int probe = largest; probe > 1; probe >>= 1) {
        ++bitsCount;
    }
    if (bitsCount > 16) {
        throw EnigmaError("Enigma tile words must fit in sixteen bits");
    }

    // The most frequent word wins; a tie goes to the smaller value, which is
    // what the oracle's max() over (frequency, -value) selects.
    std::map<int, int> frequencies;
    for (const int value : values) {
        ++frequencies[value];
    }
    int staticTile = frequencies.begin()->first;
    int bestFrequency = -1;
    for (const auto &entry : frequencies) {
        if (entry.second > bestFrequency) {
            bestFrequency = entry.second;
            staticTile = entry.first;
        }
    }

    std::vector<int> distinct(values);
    std::sort(distinct.begin(), distinct.end());
    distinct.erase(std::unique(distinct.begin(), distinct.end()), distinct.end());

    Solver solver(values, bitsCount);
    int bestCost = 0;
    int bestIncTile = distinct.front();
    bool haveBest = false;
    for (const int candidate : distinct) {
        solver.reset();
        const int cost = solver.solve(0, candidate).cost;
        if (!haveBest || cost < bestCost) {
            bestCost = cost;
            bestIncTile = candidate;
            haveBest = true;
        }
    }

    solver.reset();
    BitWriter writer;
    std::size_t position = 0;
    int incTile = bestIncTile;
    while (true) {
        const Decision decision = solver.solve(position, incTile);
        writer.write((decision.command.mode << 4) | decision.command.repeat,
            decision.command.mode <= 1 ? 6 : 7);
        for (const int operand : decision.command.operands) {
            writer.write(operand, bitsCount);
        }
        if (decision.terminal) {
            break;
        }
        position = decision.nextPosition;
        incTile = decision.nextIncTile;
    }

    std::vector<std::uint8_t> out {
        static_cast<std::uint8_t>(bitsCount & 0xFF),
        0,
        static_cast<std::uint8_t>((bestIncTile >> 8) & 0xFF),
        static_cast<std::uint8_t>(bestIncTile & 0xFF),
        static_cast<std::uint8_t>((staticTile >> 8) & 0xFF),
        static_cast<std::uint8_t>(staticTile & 0xFF),
    };
    const auto payload = writer.toBytes();
    out.insert(out.end(), payload.begin(), payload.end());
    return out;
}

} // namespace retrolarium::core
