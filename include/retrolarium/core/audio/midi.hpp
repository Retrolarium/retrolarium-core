#pragma once

#include <cstdint>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace retrolarium::core {

// Raised when a Standard MIDI file cannot be represented by the importer that
// asked for it. Same wording as the Kit's MidiError.
class MidiError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// One note, in MIDI ticks. Velocity is deliberately absent: the engines this
// serves have none, so carrying it would only promise something the ROM cannot
// keep.
struct MidiNote final {
    int note = 0;
    int startTick = 0;
    int endTick = 0;

    [[nodiscard]] bool operator==(const MidiNote &other) const noexcept
    {
        return note == other.note && startTick == other.startTick
            && endTick == other.endTick;
    }
    [[nodiscard]] bool operator!=(const MidiNote &other) const noexcept
    {
        return !(*this == other);
    }
};

// A tempo change: the tick it takes effect at, and microseconds per quarter.
struct MidiTempo final {
    int tick = 0;
    int microsecondsPerQuarter = 0;
};

// What an importer dropped on the way in, counted per kind, so the user can be
// told what the ROM has no room for rather than finding out by listening.
struct MidiDiscarded final {
    std::string feature;
    int events = 0;
};

struct MidiTrack final {
    int division = 0;
    std::vector<MidiNote> notes;
    std::vector<MidiTempo> tempos;
    std::vector<MidiDiscarded> discardedEvents;
    int endTick = 0;
};

// Reads one channel of one track. Tempo changes are collected from every
// track, because a format-1 file usually keeps them in the first one.
[[nodiscard]] MidiTrack parseMidi(
    const std::vector<std::uint8_t> &data, int trackIndex, int channel);

// Reads one channel across every track, which is what a format-1 file needs.
[[nodiscard]] MidiTrack parseMidiChannel(
    const std::vector<std::uint8_t> &data, int channel);

// Where a tick falls in seconds, following the tempo changes up to it.
[[nodiscard]] double midiTickSeconds(
    int tick, int division, const std::vector<MidiTempo> &tempos);

// Writes one monophonic channel as a format-0 file.
[[nodiscard]] std::vector<std::uint8_t> encodeMidi(
    const std::vector<MidiNote> &notes, int division = 960,
    int tempo = 500000);

// The same for several channels in one track, each monophonic on its own.
// `endTick` pads the track out past the last note when it is not negative.
[[nodiscard]] std::vector<std::uint8_t> encodeMidiChannels(
    const std::map<int, std::vector<MidiNote>> &channels, int division = 960,
    int tempo = 500000, int endTick = -1);

} // namespace retrolarium::core
