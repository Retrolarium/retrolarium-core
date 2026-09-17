// Cross-language parity for Standard MIDI.
//
// The corpus comes from retrolarium/tools/generate-midi-parity.py and is
// generated from the Kit's midi module, which stays the oracle.
//
// Files are carried whole: they are small, and the point of each is a byte
// sequence the reader has to make a decision about.

#include <retrolarium/core/midi.hpp>

#include <cstdint>
#include <fstream>
#include <iostream>
#include <map>
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
    for (std::size_t index = 0; index + 1 < text.size(); index += 2) {
        const int high = nibble(text[index]);
        const int low = nibble(text[index + 1]);
        if (high < 0 || low < 0) return {};
        out.push_back(static_cast<std::uint8_t>(high * 16 + low));
    }
    return out;
}

std::string toHex(const std::vector<std::uint8_t> &bytes)
{
    static constexpr char kDigits[] = "0123456789abcdef";
    std::string out;
    for (const std::uint8_t byte : bytes) {
        out.push_back(kDigits[(byte >> 4) & 0xF]);
        out.push_back(kDigits[byte & 0xF]);
    }
    return out;
}

std::string fromHexText(const std::string &text)
{
    const std::vector<std::uint8_t> bytes = fromHex(text);
    return {bytes.begin(), bytes.end()};
}

// What the corpus says one parse should produce.
struct Expected final {
    int division = 0;
    int endTick = 0;
    std::vector<retrolarium::core::MidiNote> notes;
    std::vector<retrolarium::core::MidiTempo> tempos;
    std::vector<retrolarium::core::MidiDiscarded> discarded;
    std::string seconds;
};

void checkParsed(const std::string &name,
    const retrolarium::core::MidiTrack &parsed, const Expected &expected)
{
    if (parsed.division != expected.division
        || parsed.endTick != expected.endTick) {
        report(name + " division or end tick differs from the oracle");
    }
    if (parsed.notes != expected.notes) {
        report(name + " notes differ from the oracle");
    }
    if (parsed.tempos.size() != expected.tempos.size()) {
        report(name + " tempo count differs from the oracle");
    } else {
        for (std::size_t index = 0; index < parsed.tempos.size(); ++index) {
            if (parsed.tempos[index].tick != expected.tempos[index].tick
                || parsed.tempos[index].microsecondsPerQuarter
                    != expected.tempos[index].microsecondsPerQuarter) {
                report(name + " tempo differs from the oracle");
            }
        }
    }
    if (parsed.discardedEvents.size() != expected.discarded.size()) {
        report(name + " discarded-event kinds differ from the oracle");
    } else {
        for (std::size_t index = 0; index < parsed.discardedEvents.size();
            ++index) {
            if (parsed.discardedEvents[index].feature
                    != expected.discarded[index].feature
                || parsed.discardedEvents[index].events
                    != expected.discarded[index].events) {
                report(name + " discarded events differ from the oracle");
            }
        }
    }

    // Nine decimals, which is finer than any tempo the corpus uses can move.
    std::ostringstream seconds;
    seconds.setf(std::ios::fixed);
    seconds.precision(9);
    seconds << retrolarium::core::midiTickSeconds(
        parsed.endTick, parsed.division, parsed.tempos);
    if (seconds.str() != expected.seconds) {
        report(name + " ends at " + seconds.str() + " seconds, the Kit says "
            + expected.seconds);
    }
}

} // namespace

int main(int argc, char *argv[])
{
    if (argc != 2) {
        std::cerr << "usage: retrolarium-core-midi-golden-tests <corpus.txt>\n";
        return 2;
    }
    std::ifstream stream(argv[1]);
    if (!stream) {
        std::cerr << "cannot open corpus " << argv[1] << '\n';
        return 2;
    }

    enum class Mode { None, Parse, Channel, Reject, Encode };
    Mode mode = Mode::None;
    std::string name;
    int trackIndex = 0;
    int channel = 0;
    std::vector<std::uint8_t> file;
    Expected expected;
    std::string message;
    int division = 0;
    int tempo = 0;
    int endTick = -1;
    std::map<int, std::vector<retrolarium::core::MidiNote>> inputs;

    int parses = 0;
    int rejects = 0;
    int encodes = 0;
    std::string line;
    bool firstLine = true;

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
            if (value != "retrolarium.midi-parity") {
                report("unexpected corpus schema " + value);
            }
        } else if (key == "schema_version" || key == "generator") {
            continue;
        } else if (key == "case" || key == "reject") {
            mode = key == "case" ? Mode::Parse : Mode::Reject;
            fields >> name >> trackIndex >> channel;
            expected = Expected {};
            message.clear();
        } else if (key == "channel-case") {
            mode = Mode::Channel;
            fields >> name >> channel;
            expected = Expected {};
        } else if (key == "encode-case") {
            mode = Mode::Encode;
            fields >> name >> division >> tempo >> endTick;
            inputs.clear();
        } else if (key == "file") {
            std::string value;
            fields >> value;
            file = fromHex(value);
        } else if (key == "division") {
            fields >> expected.division;
        } else if (key == "end-tick") {
            fields >> expected.endTick;
        } else if (key == "note") {
            retrolarium::core::MidiNote note;
            fields >> note.note >> note.startTick >> note.endTick;
            expected.notes.push_back(note);
        } else if (key == "tempo") {
            retrolarium::core::MidiTempo item;
            fields >> item.tick >> item.microsecondsPerQuarter;
            expected.tempos.push_back(item);
        } else if (key == "discarded") {
            retrolarium::core::MidiDiscarded item;
            fields >> item.feature >> item.events;
            expected.discarded.push_back(item);
        } else if (key == "seconds") {
            fields >> expected.seconds;
        } else if (key == "message") {
            std::string value;
            fields >> value;
            message = fromHexText(value);
        } else if (key == "input") {
            int target = 0;
            retrolarium::core::MidiNote note;
            fields >> target >> note.note >> note.startTick >> note.endTick;
            inputs[target].push_back(note);
        } else if (key == "end") {
            try {
                if (mode == Mode::Parse) {
                    ++parses;
                    checkParsed(name,
                        retrolarium::core::parseMidi(file, trackIndex, channel),
                        expected);
                } else if (mode == Mode::Channel) {
                    ++parses;
                    checkParsed(name,
                        retrolarium::core::parseMidiChannel(file, channel),
                        expected);
                } else if (mode == Mode::Reject) {
                    ++rejects;
                    try {
                        static_cast<void>(retrolarium::core::parseMidi(
                            file, trackIndex, channel));
                        report(name + " parsed; the Kit refuses it: " + message);
                    } catch (const retrolarium::core::MidiError &error) {
                        const std::string actual = error.what();
                        if (actual != message) {
                            report(name + " refused with [" + actual
                                + "], the Kit says [" + message + "]");
                        }
                    }
                } else if (mode == Mode::Encode) {
                    ++encodes;
                    const auto encoded = retrolarium::core::encodeMidiChannels(
                        inputs, division, tempo, endTick);
                    if (encoded != file) {
                        report(name + " encoded " + toHex(encoded)
                            + ", the Kit writes " + toHex(file));
                    }
                    // The one-channel spelling has to agree with it.
                    if (inputs.size() == 1 && inputs.count(0) != 0
                        && endTick < 0) {
                        const auto single = retrolarium::core::encodeMidi(
                            inputs.at(0), division, tempo);
                        if (single != encoded) {
                            report(name + " one-channel form differs");
                        }
                    }
                }
            } catch (const std::exception &error) {
                report(name + " raised: " + error.what());
            }
            mode = Mode::None;
        } else {
            report("unknown corpus key \"" + key + "\"");
        }
    }

    if (parses == 0 || encodes == 0) {
        std::cerr << "corpus carried no parses or no encodes\n";
        return 2;
    }
    if (failures != 0) {
        std::cerr << failures << " MIDI parity check(s) failed\n";
        return 1;
    }
    std::cout << "MIDI parity: " << parses << " parses, " << rejects
              << " refusals, " << encodes << " encodes\n";
    return 0;
}
