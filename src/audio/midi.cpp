// Standard MIDI, read and written without a library.
//
// Only what an engine-aware importer can use survives the read: monophonic
// notes and the tempo map. Everything else is counted and dropped, because a
// ROM channel has no way to express it and pretending otherwise would lose the
// difference silently.

#include <retrolarium/core/audio/midi.hpp>

#include <algorithm>
#include <set>

namespace retrolarium::core {
namespace {

[[noreturn]] void fail(const std::string &message)
{
    throw MidiError(message);
}

std::string hexByte(int value)
{
    static constexpr char kDigits[] = "0123456789ABCDEF";
    return std::string {kDigits[(value >> 4) & 0xF], kDigits[value & 0xF]};
}

// A variable-length quantity: seven bits a byte, high bit meaning "more".
int readVarlen(const std::vector<std::uint8_t> &data, std::size_t &cursor)
{
    int value = 0;
    for (int step = 0; step < 4; ++step) {
        if (cursor >= data.size()) {
            fail("truncated MIDI variable-length value");
        }
        const int byte = data[cursor];
        ++cursor;
        value = (value << 7) | (byte & 0x7F);
        if (byte < 0x80) return value;
    }
    fail("MIDI variable-length value exceeds four bytes");
}

std::vector<std::uint8_t> writeVarlen(int value)
{
    if (value < 0 || value > 0x0FFFFFFF) {
        fail("MIDI delta time is outside the variable-length range");
    }
    std::vector<std::uint8_t> encoded {static_cast<std::uint8_t>(value & 0x7F)};
    int remaining = value >> 7;
    while (remaining != 0) {
        encoded.insert(encoded.begin(),
            static_cast<std::uint8_t>(0x80 | (remaining & 0x7F)));
        remaining >>= 7;
    }
    return encoded;
}

int readBigEndian(
    const std::vector<std::uint8_t> &data, std::size_t offset, std::size_t size)
{
    int value = 0;
    for (std::size_t index = 0; index < size; ++index) {
        value = (value << 8) | data[offset + index];
    }
    return value;
}

bool startsWith(const std::vector<std::uint8_t> &data, std::size_t offset,
    const char *tag)
{
    for (std::size_t index = 0; index < 4; ++index) {
        if (offset + index >= data.size()
            || data[offset + index] != static_cast<std::uint8_t>(tag[index])) {
            return false;
        }
    }
    return true;
}

struct TrackEvents final {
    std::vector<MidiNote> notes;
    std::vector<MidiTempo> tempos;
    std::map<std::string, int> discarded;
    int endTick = 0;
};

// One track's events. `collectChannel` is false for the tracks read only for
// their tempo map.
TrackEvents trackEvents(
    const std::vector<std::uint8_t> &data, int channel, bool collectChannel)
{
    TrackEvents result;
    std::size_t cursor = 0;
    int tick = 0;
    bool haveRunningStatus = false;
    int runningStatus = 0;
    // At most one note sounds at a time, so the map holds one entry; it is a
    // map because a note-off names the note it ends.
    std::map<int, int> active;

    while (cursor < data.size()) {
        tick += readVarlen(data, cursor);
        if (cursor >= data.size()) {
            fail("truncated MIDI event");
        }
        int status = data[cursor];
        if (status < 0x80) {
            // Running status: the event repeats the last one's kind.
            if (!haveRunningStatus) {
                fail("MIDI running status has no channel event");
            }
            status = runningStatus;
        } else {
            ++cursor;
            if (status < 0xF0) {
                runningStatus = status;
                haveRunningStatus = true;
            } else {
                haveRunningStatus = false;
            }
        }

        if (status == 0xFF) {
            if (cursor >= data.size()) {
                fail("truncated MIDI meta event");
            }
            const int kind = data[cursor];
            ++cursor;
            const int length = readVarlen(data, cursor);
            if (cursor + static_cast<std::size_t>(length) > data.size()) {
                fail("truncated MIDI meta payload");
            }
            if (kind == 0x51) {
                if (length != 3) {
                    fail("MIDI tempo event must contain three bytes");
                }
                const int tempo = readBigEndian(data, cursor, 3);
                if (tempo == 0) {
                    fail("MIDI tempo must be positive");
                }
                result.tempos.push_back({tick, tempo});
            }
            cursor += static_cast<std::size_t>(length);
            if (kind == 0x2F) break;
            continue;
        }
        if (status == 0xF0 || status == 0xF7) {
            const int length = readVarlen(data, cursor);
            if (cursor + static_cast<std::size_t>(length) > data.size()) {
                fail("truncated MIDI system-exclusive event");
            }
            cursor += static_cast<std::size_t>(length);
            continue;
        }

        const int event = status & 0xF0;
        const int eventChannel = status & 0x0F;
        if (event < 0x80 || event > 0xE0) {
            fail("unsupported MIDI status $" + hexByte(status));
        }
        const std::size_t length =
            (event == 0xC0 || event == 0xD0) ? 1 : 2;
        if (cursor + length > data.size()) {
            fail("truncated MIDI channel event");
        }
        const std::vector<std::uint8_t> payload(
            data.begin() + static_cast<std::ptrdiff_t>(cursor),
            data.begin() + static_cast<std::ptrdiff_t>(cursor + length));
        cursor += length;
        if (eventChannel != channel || !collectChannel) continue;

        if (event != 0x80 && event != 0x90) {
            static const std::map<int, std::string> kFeatures {
                {0xA0, "polyphonic_aftertouch"}, {0xB0, "controller"},
                {0xC0, "instrument"}, {0xD0, "channel_aftertouch"},
                {0xE0, "pitch_bend"},
            };
            result.discarded[kFeatures.at(event)] += 1;
            continue;
        }

        const int note = payload[0];
        // A note-on with zero velocity is how most writers spell note-off.
        const bool isOn = event == 0x90 && payload[1] != 0;
        if (isOn) {
            if (!active.empty()) {
                fail("MIDI import requires a monophonic channel");
            }
            active[note] = tick;
        } else {
            const auto found = active.find(note);
            if (found != active.end()) {
                const int start = found->second;
                active.erase(found);
                if (tick <= start) {
                    fail("MIDI notes must have positive duration");
                }
                result.notes.push_back({note, start, tick});
            }
        }
    }

    if (!active.empty()) {
        fail("MIDI note remains active at end of track");
    }
    if (!result.notes.empty()) {
        result.discarded["velocity"] = static_cast<int>(result.notes.size());
    }
    result.endTick = tick;
    return result;
}

std::vector<MidiDiscarded> sortedDiscarded(const std::map<std::string, int> &counts)
{
    std::vector<MidiDiscarded> result;
    for (const auto &entry : counts) {
        result.push_back({entry.first, entry.second});
    }
    return result;
}

} // namespace

MidiTrack parseMidi(
    const std::vector<std::uint8_t> &data, int trackIndex, int channel)
{
    if (channel < 0 || channel > 15) {
        fail("MIDI channel must be in 0..15");
    }
    if (data.size() < 14 || !startsWith(data, 0, "MThd")) {
        fail("not a Standard MIDI file");
    }
    const int headerSize = readBigEndian(data, 4, 4);
    if (headerSize < 6
        || 8 + static_cast<std::size_t>(headerSize) > data.size()) {
        fail("invalid MIDI header length");
    }
    const int trackCount = readBigEndian(data, 10, 2);
    const int division = readBigEndian(data, 12, 2);
    if (trackCount == 0 || division == 0) {
        fail("MIDI track count and division must be positive");
    }
    if ((division & 0x8000) != 0) {
        fail("SMPTE MIDI timing is not supported");
    }
    if (trackIndex < 0 || trackIndex >= trackCount) {
        fail("MIDI track index is out of range");
    }

    std::size_t cursor = 8 + static_cast<std::size_t>(headerSize);
    std::vector<MidiNote> selected;
    std::map<std::string, int> selectedDiscarded;
    int selectedEndTick = 0;
    std::vector<MidiTempo> tempos;
    for (int index = 0; index < trackCount; ++index) {
        if (cursor + 8 > data.size() || !startsWith(data, cursor, "MTrk")) {
            fail("missing MIDI track chunk");
        }
        const std::size_t length =
            static_cast<std::size_t>(readBigEndian(data, cursor + 4, 4));
        if (cursor + 8 + length > data.size()) {
            fail("truncated MIDI track");
        }
        const std::vector<std::uint8_t> payload(
            data.begin() + static_cast<std::ptrdiff_t>(cursor + 8),
            data.begin() + static_cast<std::ptrdiff_t>(cursor + 8 + length));
        const TrackEvents events =
            trackEvents(payload, channel, index == trackIndex);
        tempos.insert(tempos.end(), events.tempos.begin(), events.tempos.end());
        if (index == trackIndex) {
            selected = events.notes;
            selectedDiscarded = events.discarded;
            selectedEndTick = events.endTick;
        }
        cursor += 8 + length;
    }
    if (cursor != data.size()) {
        fail("MIDI file has trailing data");
    }

    std::sort(tempos.begin(), tempos.end(),
        [](const MidiTempo &left, const MidiTempo &right) {
            return left.tick != right.tick
                ? left.tick < right.tick
                : left.microsecondsPerQuarter < right.microsecondsPerQuarter;
        });

    MidiTrack track;
    track.division = division;
    track.notes = std::move(selected);
    track.tempos = std::move(tempos);
    track.discardedEvents = sortedDiscarded(selectedDiscarded);
    track.endTick = selectedEndTick;
    return track;
}

MidiTrack parseMidiChannel(const std::vector<std::uint8_t> &data, int channel)
{
    if (data.size() < 14 || !startsWith(data, 0, "MThd")) {
        fail("not a Standard MIDI file");
    }
    const int trackCount = readBigEndian(data, 10, 2);

    std::vector<MidiNote> combined;
    std::map<std::string, int> discarded;
    bool haveReference = false;
    MidiTrack reference;
    int endTick = 0;
    for (int index = 0; index < trackCount; ++index) {
        const MidiTrack parsed = parseMidi(data, index, channel);
        if (!haveReference) {
            reference = parsed;
            haveReference = true;
        }
        combined.insert(
            combined.end(), parsed.notes.begin(), parsed.notes.end());
        endTick = std::max(endTick, parsed.endTick);
        for (const MidiDiscarded &item : parsed.discardedEvents) {
            discarded[item.feature] += item.events;
        }
    }

    std::sort(combined.begin(), combined.end(),
        [](const MidiNote &left, const MidiNote &right) {
            if (left.startTick != right.startTick) {
                return left.startTick < right.startTick;
            }
            if (left.endTick != right.endTick) return left.endTick < right.endTick;
            return left.note < right.note;
        });
    // Each track may be monophonic on its own and still overlap another.
    int previousEnd = 0;
    for (const MidiNote &note : combined) {
        if (note.startTick < previousEnd) {
            fail("MIDI import requires a monophonic channel across all tracks");
        }
        previousEnd = note.endTick;
    }

    MidiTrack track;
    track.division = reference.division;
    track.notes = std::move(combined);
    track.tempos = reference.tempos;
    track.discardedEvents = sortedDiscarded(discarded);
    track.endTick = endTick;
    return track;
}

double midiTickSeconds(
    int tick, int division, const std::vector<MidiTempo> &tempos)
{
    double elapsed = 0.0;
    int previousTick = 0;
    // The default tempo a file without one means: 120 quarters a minute.
    int tempo = 500000;
    for (const MidiTempo &change : tempos) {
        if (change.tick >= tick) break;
        if (change.tick < previousTick) {
            fail("MIDI tempo events are not ordered");
        }
        elapsed += static_cast<double>(change.tick - previousTick) * tempo
            / (static_cast<double>(division) * 1000000.0);
        previousTick = change.tick;
        tempo = change.microsecondsPerQuarter;
    }
    return elapsed + static_cast<double>(tick - previousTick) * tempo
        / (static_cast<double>(division) * 1000000.0);
}

std::vector<std::uint8_t> encodeMidi(
    const std::vector<MidiNote> &notes, int division, int tempo)
{
    return encodeMidiChannels({{0, notes}}, division, tempo);
}

std::vector<std::uint8_t> encodeMidiChannels(
    const std::map<int, std::vector<MidiNote>> &channels, int division,
    int tempo, int endTick)
{
    if (division < 1 || division >= 0x8000) {
        fail("MIDI division must be in 1..32767");
    }
    if (tempo < 1 || tempo > 0xFFFFFF) {
        fail("MIDI tempo must be in 1..16777215 microseconds");
    }

    // tick, then off before on at the same tick, then channel, then note - the
    // order the Kit's sort produces, and the one the bytes depend on.
    struct Event final {
        int tick = 0;
        int kind = 0;
        int channel = 0;
        int note = 0;
    };
    std::vector<Event> events;
    int latestTick = 0;
    for (const auto &entry : channels) {
        const int channel = entry.first;
        if (channel < 0 || channel > 15) {
            fail("MIDI channel must be in 0..15");
        }
        std::vector<MidiNote> ordered = entry.second;
        std::sort(ordered.begin(), ordered.end(),
            [](const MidiNote &left, const MidiNote &right) {
                return left.startTick != right.startTick
                    ? left.startTick < right.startTick
                    : left.endTick < right.endTick;
            });
        int previousEnd = 0;
        for (const MidiNote &note : ordered) {
            if (note.note < 0 || note.note > 127) {
                fail("MIDI note is outside 0..127");
            }
            if (note.startTick < previousEnd) {
                fail("MIDI export requires a monophonic note sequence per channel");
            }
            if (note.endTick <= note.startTick) {
                fail("MIDI notes must have positive duration");
            }
            events.push_back({note.startTick, 1, channel, note.note});
            events.push_back({note.endTick, 0, channel, note.note});
            previousEnd = note.endTick;
            latestTick = std::max(latestTick, note.endTick);
        }
    }
    if (endTick >= 0) {
        if (endTick < latestTick) {
            fail("MIDI end tick precedes a note");
        }
        latestTick = endTick;
    }
    std::sort(events.begin(), events.end(),
        [](const Event &left, const Event &right) {
            if (left.tick != right.tick) return left.tick < right.tick;
            if (left.kind != right.kind) return left.kind < right.kind;
            if (left.channel != right.channel) return left.channel < right.channel;
            return left.note < right.note;
        });

    std::vector<std::uint8_t> track {0x00, 0xFF, 0x51, 0x03,
        static_cast<std::uint8_t>((tempo >> 16) & 0xFF),
        static_cast<std::uint8_t>((tempo >> 8) & 0xFF),
        static_cast<std::uint8_t>(tempo & 0xFF)};
    int cursor = 0;
    for (const Event &event : events) {
        const std::vector<std::uint8_t> delta = writeVarlen(event.tick - cursor);
        track.insert(track.end(), delta.begin(), delta.end());
        if (event.kind == 0) {
            track.push_back(static_cast<std::uint8_t>(0x80 | event.channel));
            track.push_back(static_cast<std::uint8_t>(event.note));
            track.push_back(0);
        } else {
            track.push_back(static_cast<std::uint8_t>(0x90 | event.channel));
            track.push_back(static_cast<std::uint8_t>(event.note));
            // A fixed velocity: the engines have none, so any value here is a
            // convention rather than information.
            track.push_back(100);
        }
        cursor = event.tick;
    }
    const std::vector<std::uint8_t> tail = writeVarlen(latestTick - cursor);
    track.insert(track.end(), tail.begin(), tail.end());
    track.insert(track.end(), {0xFF, 0x2F, 0x00});

    const auto big = [](std::vector<std::uint8_t> &out, int value,
                         std::size_t size) {
        for (std::size_t index = size; index-- > 0;) {
            out.push_back(static_cast<std::uint8_t>((value >> (index * 8)) & 0xFF));
        }
    };
    std::vector<std::uint8_t> out {'M', 'T', 'h', 'd'};
    big(out, 6, 4);
    big(out, 0, 2);
    big(out, 1, 2);
    big(out, division, 2);
    out.insert(out.end(), {'M', 'T', 'r', 'k'});
    big(out, static_cast<int>(track.size()), 4);
    out.insert(out.end(), track.begin(), track.end());
    return out;
}

} // namespace retrolarium::core
