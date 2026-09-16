#pragma once

#include <retrolarium/core/game_profile.hpp>

#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace retrolarium::core {

// Raised when a profile or a ROM image cannot produce the bytes a resource
// declares. Same wording as the Kit's NesResourceError.
class ResourceSourceError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// One run of bytes a resource occupies. An empty payloadId means the span is
// addressed in the source image itself rather than inside a named payload.
struct ResourceSpan final {
    std::size_t offset = 0;
    std::size_t size = 0;
    std::string payloadId;
};

// The same run, carrying the bytes that will replace it.
struct EncodedSpan final {
    std::size_t offset = 0;
    std::vector<std::uint8_t> replacement;
    std::string payloadId;
};

// What the container tells us about the image, which today is only whether it
// declares a mapper to cross-check against the profile.
struct RevisionImage final {
    bool hasMapper = false;
    int mapper = 0;
};

// Checks the image really is the container the revision declares.
[[nodiscard]] RevisionImage validateRevisionContainer(
    const std::vector<std::uint8_t> &source, const RevisionSpec &revision);

// The payload's bytes, with its declared size and SHA-1 verified: a profile
// that no longer describes the ROM in front of it must not silently decode.
[[nodiscard]] std::vector<std::uint8_t> payloadSource(
    const std::vector<std::uint8_t> &source, const PayloadSpec &payload);

// The bytes a resource is addressed against: its named payload, or the whole
// source image when it has none.
[[nodiscard]] std::vector<std::uint8_t> resourceSource(
    const std::vector<std::uint8_t> &source, const GameProfile &profile,
    const RevisionSpec &revision, const ResourceSpec &resource);

[[nodiscard]] std::vector<std::uint8_t> readResourceSpans(
    const std::vector<std::uint8_t> &source, const GameProfile &profile,
    const RevisionSpec &revision, const ResourceSpec &resource,
    const std::vector<ResourceSpan> &spans);

// Cuts an encoded stream back up along the layout it was read with.
[[nodiscard]] std::vector<EncodedSpan> encodedResourceSpans(
    const std::vector<std::uint8_t> &payload,
    const std::vector<ResourceSpan> &spans);

// One run of replacement bytes and where it goes in the file.
struct PhysicalReplacement final {
    std::size_t fileOffset = 0;
    std::vector<std::uint8_t> bytes;
};

// Turns payload-relative replacements into file offsets. An FDS payload is
// spread across several file records, so one span can come back as several.
[[nodiscard]] std::vector<PhysicalReplacement> physicalReplacements(
    const std::vector<std::uint8_t> &source, const GameProfile &profile,
    const RevisionSpec &revision, const ResourceSpec &resource,
    const std::vector<EncodedSpan> &replacements);

// The single span a fixed-size resource declares through its parameters.
[[nodiscard]] ResourceSpan resourceParameterSpan(
    const ResourceSpec &resource, std::size_t expectedSize);

// Some palettes are stored several times over; this is the list of offsets per
// entry, or an empty result when the resource declares none.
[[nodiscard]] std::vector<std::vector<std::size_t>> replicatedPaletteOffsets(
    const ResourceSpec &resource, std::size_t entries, bool &declared);

} // namespace retrolarium::core
