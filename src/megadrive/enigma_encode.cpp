#include <retrolarium/core/megadrive/enigma.hpp>

#include <algorithm>
#include <cstdint>
#include <map>
#include <unordered_map>
#include <utility>

namespace retrolarium::core {
namespace {

// One emitted command: its mode and its repeat field. The tile words it
// writes inline (modes 4 to 6 one, mode 7 a literal run) are the map's own
// from the command's position, read when it is written.
struct Command final {
    int mode = 0;
    int repeat = 0;
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

std::vector<int> wordsFromBytes(const std::vector<std::uint8_t>& data) {
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

int runLength(const std::vector<int>& values, std::size_t position, int step) {
    int length = 1;
    while (length < 16 && position + static_cast<std::size_t>(length) < values.size() &&
           values[position + static_cast<std::size_t>(length)] == ((values[position] + step * length) & 0xFFFF)) {
        ++length;
    }
    return length;
}

// A command the search may emit at a state: its own cost and the state it
// leads to, whose best cost adds to it.
struct Candidate final {
    int cost = 0;
    Command command;
    std::size_t nextPosition = 0;
    int nextIncTile = 0;
};

class Solver final {
public:
    Solver(const std::vector<int>& values, int bitsCount) : values_(values), bitsCount_(bitsCount) {}

    // Elements of an unordered_map keep their address through a rehash, so
    // a reference handed to a caller survives later inserts.
    //
    // The search is the oracle's recursion walked on an explicit stack: a
    // state's candidates are listed in the oracle's order, each waits for the
    // state it leads to, and ties keep the first. A map as long as a plane
    // (thousands of words) would otherwise nest that many native calls.
    const Decision& solve(std::size_t position, int incTile) {
        if (const auto found = memo_.find(key(position, incTile)); found != memo_.end()) {
            return found->second;
        }
        std::vector<Frame> stack;
        stack.push_back(open(position, incTile));
        while (!stack.empty()) {
            Frame& frame = stack.back();
            if (frame.next < frame.candidates.size()) {
                const Candidate& candidate = frame.candidates[frame.next];
                const auto child = memo_.find(key(candidate.nextPosition, candidate.nextIncTile));
                if (child == memo_.end()) {
                    // Opened after the reference is used: push_back may move frames.
                    Frame opened = open(candidate.nextPosition, candidate.nextIncTile);
                    stack.push_back(std::move(opened));
                    continue;
                }
                const int cost = candidate.cost + child->second.cost;
                if (!frame.haveBest || cost < frame.best.cost) {
                    frame.best =
                        Decision{cost, candidate.command, candidate.nextPosition, candidate.nextIncTile, false};
                    frame.haveBest = true;
                }
                ++frame.next;
                continue;
            }
            memo_.emplace(key(frame.position, frame.incTile), std::move(frame.best));
            stack.pop_back();
        }
        return memo_.find(key(position, incTile))->second;
    }

private:
    struct Frame final {
        std::size_t position = 0;
        int incTile = 0;
        std::vector<Candidate> candidates;
        std::size_t next = 0;
        Decision best;
        bool haveBest = false;
    };

    static std::uint64_t key(std::size_t position, int incTile) {
        return (static_cast<std::uint64_t>(position) << 17) | static_cast<std::uint64_t>(incTile & 0xFFFF);
    }

    // A state's candidates in the oracle's order; the end of the map is the
    // terminator alone, decided at once.
    Frame open(std::size_t position, int incTile) {
        Frame frame;
        frame.position = position;
        frame.incTile = incTile;
        if (position == values_.size()) {
            frame.best.cost = 7;
            frame.best.command = Command{7, 15};
            frame.best.terminal = true;
            frame.haveBest = true;
            return frame;
        }
        if (values_[position] == incTile) {
            int length = 0;
            while (length < 16 && position + static_cast<std::size_t>(length) < values_.size() &&
                   values_[position + static_cast<std::size_t>(length)] == ((incTile + length) & 0xFFFF)) {
                ++length;
            }
            for (int count = 1; count <= length; ++count) {
                frame.candidates.push_back(Candidate{
                    6, Command{0, count - 1}, position + static_cast<std::size_t>(count), (incTile + count) & 0xFFFF});
            }
        }
        static constexpr int kModes[3]{4, 5, 6};
        static constexpr int kSteps[3]{0, 1, -1};
        for (int index = 0; index < 3; ++index) {
            const int maximum = runLength(values_, position, kSteps[index]);
            for (int count = 1; count <= maximum; ++count) {
                frame.candidates.push_back(Candidate{7 + bitsCount_, Command{kModes[index], count - 1},
                                                     position + static_cast<std::size_t>(count), incTile});
            }
        }
        const int literalLimit = static_cast<int>(std::min<std::size_t>(15, values_.size() - position));
        for (int count = 1; count <= literalLimit; ++count) {
            frame.candidates.push_back(Candidate{7 + count * bitsCount_, Command{7, count - 1},
                                                 position + static_cast<std::size_t>(count), incTile});
        }
        return frame;
    }

    const std::vector<int>& values_;
    int bitsCount_ = 0;
    std::unordered_map<std::uint64_t, Decision> memo_;
};

class BitWriter final {
public:
    void write(int value, int count) {
        for (int shift = count - 1; shift >= 0; --shift) {
            bits_.push_back((value >> shift) & 1);
        }
    }

    [[nodiscard]] std::vector<std::uint8_t> toBytes() const {
        std::vector<std::uint8_t> out;
        for (std::size_t index = 0; index < bits_.size(); index += 8) {
            int value = 0;
            for (std::size_t offset = 0; offset < 8; ++offset) {
                value = (value << 1) | (index + offset < bits_.size() ? bits_[index + offset] : 0);
            }
            out.push_back(static_cast<std::uint8_t>(value));
        }
        return out;
    }

private:
    std::vector<int> bits_;
};

}  // namespace

std::vector<std::uint8_t> enigmaCompress(const std::vector<std::uint8_t>& data) {
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
    for (const auto& entry : frequencies) {
        if (entry.second > bestFrequency) {
            bestFrequency = entry.second;
            staticTile = entry.first;
        }
    }

    std::vector<int> distinct(values);
    std::sort(distinct.begin(), distinct.end());
    distinct.erase(std::unique(distinct.begin(), distinct.end()), distinct.end());

    // One memo for every starting tile: the best command at a state (a
    // position and the incrementing tile there) is the same whichever tile
    // the search started from, so a state solved for one start serves the
    // others. The choices, and so the output, are unchanged.
    Solver solver(values, bitsCount);
    int bestCost = 0;
    int bestIncTile = distinct.front();
    bool haveBest = false;
    for (const int candidate : distinct) {
        const int cost = solver.solve(0, candidate).cost;
        if (!haveBest || cost < bestCost) {
            bestCost = cost;
            bestIncTile = candidate;
            haveBest = true;
        }
    }

    BitWriter writer;
    std::size_t position = 0;
    int incTile = bestIncTile;
    while (true) {
        const Decision decision = solver.solve(position, incTile);
        writer.write((decision.command.mode << 4) | decision.command.repeat, decision.command.mode <= 1 ? 6 : 7);
        // Modes 4 to 6 write the tile at the position, a literal (mode 7
        // short of the terminator) the run of tiles from it.
        const int mode = decision.command.mode;
        const int operands = decision.terminal        ? 0
                             : mode >= 4 && mode <= 6 ? 1
                             : mode == 7              ? decision.command.repeat + 1
                                                      : 0;
        for (int index = 0; index < operands; ++index) {
            writer.write(values[position + static_cast<std::size_t>(index)], bitsCount);
        }
        if (decision.terminal) {
            break;
        }
        position = decision.nextPosition;
        incTile = decision.nextIncTile;
    }

    std::vector<std::uint8_t> out{
        static_cast<std::uint8_t>(bitsCount & 0xFF),          0,
        static_cast<std::uint8_t>((bestIncTile >> 8) & 0xFF), static_cast<std::uint8_t>(bestIncTile & 0xFF),
        static_cast<std::uint8_t>((staticTile >> 8) & 0xFF),  static_cast<std::uint8_t>(staticTile & 0xFF),
    };
    const auto payload = writer.toBytes();
    out.insert(out.end(), payload.begin(), payload.end());
    return out;
}

}  // namespace retrolarium::core
