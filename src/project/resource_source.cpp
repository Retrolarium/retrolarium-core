#include <retrolarium/core/project/resource_source.hpp>

#include <retrolarium/core/fds/fds.hpp>
#include <retrolarium/core/nes/ines.hpp>
#include <retrolarium/core/hash/sha1.hpp>

#include <map>
#include <set>

namespace retrolarium::core {
namespace {

[[noreturn]] void fail(const std::string &message)
{
    throw ResourceSourceError(message);
}

constexpr std::size_t kPlayChoiceInstructionRom = 0x2000;

std::size_t requireInteger(const Value *value, const std::string &name,
    std::int64_t minimum = 0)
{
    // Python rejects a bool here even though it is an int, and JSON keeps the
    // two apart, so the check is just the type.
    if (value == nullptr || !value->isInteger() || value->asInteger() < minimum) {
        fail(name + " must be an integer >= " + std::to_string(minimum));
    }
    return static_cast<std::size_t>(value->asInteger());
}

const Value *parameter(const ResourceSpec &resource, const std::string &name)
{
    const auto found = resource.parameters.find(name);
    return found == resource.parameters.end() ? nullptr : &found->second;
}

} // namespace

RevisionImage validateRevisionContainer(
    const std::vector<std::uint8_t> &source, const RevisionSpec &revision)
{
    RevisionImage result;
    if (revision.container == "ines") {
        const InesImage image = parseInes(source);
        result.hasMapper = true;
        result.mapper = image.mapper;
        return result;
    }
    if (revision.container == "ines-pc10") {
        const auto parsed = parseInesPrefix(source);
        if (parsed.second.size() != kPlayChoiceInstructionRom) {
            fail("PlayChoice-10 container must have an 8192-byte instruction ROM");
        }
        result.hasMapper = true;
        result.mapper = parsed.first.mapper;
        return result;
    }
    if (revision.container == "ines-vs") {
        // Vs. images are iNES-shaped but not iNES-parsable, so only the size
        // and the signature are contractual.
        static const std::vector<std::uint8_t> kSignature {'N', 'E', 'S', 0x1A};
        if (source.size() != static_cast<std::size_t>(revision.size)
            || source.size() < kSignature.size()
            || !std::equal(kSignature.begin(), kSignature.end(), source.begin())) {
            fail("Vs. container size or iNES signature differs from its profile");
        }
        return result;
    }
    if (revision.container == "fds") {
        try {
            static_cast<void>(parseFdsSide(source));
        } catch (const FdsError &error) {
            fail(error.what());
        }
        return result;
    }
    fail("NES resource bundle does not support container '" + revision.container
        + "'");
}

std::vector<std::uint8_t> payloadSource(
    const std::vector<std::uint8_t> &source, const PayloadSpec &payload)
{
    std::vector<std::uint8_t> result;
    if (payload.storage == "range") {
        const std::size_t offset = static_cast<std::size_t>(payload.fileOffset);
        const std::size_t size = static_cast<std::size_t>(payload.size);
        // Python slices, which simply yields fewer bytes past the end; the
        // size check below is what turns that into a refusal.
        if (offset < source.size()) {
            const std::size_t available = source.size() - offset;
            const std::size_t take = size < available ? size : available;
            result.assign(source.begin() + static_cast<std::ptrdiff_t>(offset),
                source.begin() + static_cast<std::ptrdiff_t>(offset + take));
        }
    } else if (payload.storage == "fds-records") {
        std::vector<int> recordIds;
        for (const std::int64_t record : payload.recordIds) {
            recordIds.push_back(static_cast<int>(record));
        }
        try {
            result = fdsPayload(source, recordIds);
        } catch (const FdsError &error) {
            fail(error.what());
        }
    } else {
        fail("unsupported payload storage '" + payload.storage + "'");
    }

    if (result.size() != static_cast<std::size_t>(payload.size)) {
        fail("payload " + payload.payloadId + " is " + std::to_string(result.size())
            + " bytes, expected " + std::to_string(payload.size));
    }
    if (sha1Hex(result) != payload.sha1) {
        fail("payload " + payload.payloadId + " SHA-1 differs from profile");
    }
    return result;
}

std::vector<std::uint8_t> resourceSource(
    const std::vector<std::uint8_t> &source, const GameProfile &profile,
    const RevisionSpec &revision, const ResourceSpec &resource)
{
    if (!resource.hasPayload) {
        if (revision.container == "fds") {
            fail("FDS resource " + resource.resourceId
                + " must select a named payload");
        }
        return source;
    }
    try {
        return payloadSource(source, profile.payload(revision, resource.payload));
    } catch (const AuthoringError &error) {
        fail(error.what());
    }
}

std::vector<std::uint8_t> readResourceSpans(
    const std::vector<std::uint8_t> &source, const GameProfile &profile,
    const RevisionSpec &revision, const ResourceSpec &resource,
    const std::vector<ResourceSpan> &spans)
{
    // One payload can back many spans, and verifying its SHA-1 each time would
    // be the dominant cost of decoding.
    std::map<std::string, std::vector<std::uint8_t>> cached;
    std::vector<std::uint8_t> output;

    for (const ResourceSpan &span : spans) {
        const auto found = cached.find(span.payloadId);
        if (found == cached.end()) {
            if (span.payloadId.empty()) {
                cached.emplace(span.payloadId,
                    resourceSource(source, profile, revision, resource));
            } else {
                try {
                    cached.emplace(span.payloadId,
                        payloadSource(
                            source, profile.payload(revision, span.payloadId)));
                } catch (const AuthoringError &error) {
                    fail(error.what());
                }
            }
        }
        const std::vector<std::uint8_t> &bytes = cached.at(span.payloadId);
        if (span.offset > bytes.size() || bytes.size() - span.offset < span.size) {
            const std::string target =
                span.payloadId.empty() ? "source image" : span.payloadId;
            fail("resource " + resource.resourceId + " exceeds " + target);
        }
        output.insert(output.end(),
            bytes.begin() + static_cast<std::ptrdiff_t>(span.offset),
            bytes.begin() + static_cast<std::ptrdiff_t>(span.offset + span.size));
    }
    return output;
}

std::vector<EncodedSpan> encodedResourceSpans(
    const std::vector<std::uint8_t> &payload,
    const std::vector<ResourceSpan> &spans)
{
    std::size_t total = 0;
    for (const ResourceSpan &span : spans) {
        total += span.size;
    }
    if (payload.size() != total) {
        fail("encoded stream size differs from its span layout");
    }

    std::vector<EncodedSpan> result;
    std::size_t position = 0;
    for (const ResourceSpan &span : spans) {
        EncodedSpan encoded;
        encoded.offset = span.offset;
        encoded.payloadId = span.payloadId;
        encoded.replacement.assign(
            payload.begin() + static_cast<std::ptrdiff_t>(position),
            payload.begin() + static_cast<std::ptrdiff_t>(position + span.size));
        result.push_back(std::move(encoded));
        position += span.size;
    }
    return result;
}

std::vector<PhysicalReplacement> physicalReplacements(
    const std::vector<std::uint8_t> &source, const GameProfile &profile,
    const RevisionSpec &revision, const ResourceSpec &resource,
    const std::vector<EncodedSpan> &replacements)
{
    std::vector<PhysicalReplacement> result;
    for (const EncodedSpan &item : replacements) {
        // A resource with no payload is addressed in the file directly, and
        // then the span offset already is the file offset.
        const PayloadSpec *payload = nullptr;
        try {
            if (item.payloadId.empty()) {
                if (!resource.hasPayload) {
                    if (revision.container == "fds") {
                        fail("FDS resource " + resource.resourceId
                            + " must select a named payload");
                    }
                    result.push_back({item.offset, item.replacement});
                    continue;
                }
                payload = &profile.payload(revision, resource.payload);
            } else {
                payload = &profile.payload(revision, item.payloadId);
            }
        } catch (const AuthoringError &error) {
            fail(error.what());
        }

        if (item.offset + item.replacement.size()
            > static_cast<std::size_t>(payload->size)) {
            fail("resource " + resource.resourceId + " exceeds payload "
                + payload->payloadId);
        }

        if (payload->storage == "range") {
            result.push_back({static_cast<std::size_t>(payload->fileOffset)
                    + item.offset,
                item.replacement});
        } else if (payload->storage == "fds-records") {
            std::vector<int> recordIds;
            for (const std::int64_t record : payload->recordIds) {
                recordIds.push_back(static_cast<int>(record));
            }
            try {
                for (const FdsPayloadRange &range : fdsPayloadRanges(source,
                         recordIds, item.offset, item.replacement.size())) {
                    const auto begin = item.replacement.begin()
                        + static_cast<std::ptrdiff_t>(range.payloadOffset);
                    result.push_back({range.fileOffset,
                        {begin, begin + static_cast<std::ptrdiff_t>(range.size)}});
                }
            } catch (const FdsError &error) {
                fail(error.what());
            }
        } else {
            fail("unsupported payload storage '" + payload->storage + "'");
        }
    }
    return result;
}

ResourceSpan resourceParameterSpan(
    const ResourceSpec &resource, std::size_t expectedSize)
{
    ResourceSpan span;
    span.offset = requireInteger(parameter(resource, "file_offset"),
        resource.resourceId + ".file_offset");
    span.size = requireInteger(
        parameter(resource, "size"), resource.resourceId + ".size", 1);
    if (span.size != expectedSize) {
        fail(resource.resourceId + ".size is " + std::to_string(span.size)
            + ", expected " + std::to_string(expectedSize));
    }
    return span;
}

std::vector<std::vector<std::size_t>> replicatedPaletteOffsets(
    const ResourceSpec &resource, std::size_t entries, bool &declared)
{
    declared = false;
    const Value *raw = parameter(resource, "replicated_file_offsets");
    if (raw == nullptr || raw->isNull()) return {};
    declared = true;
    if (!raw->isArray() || raw->asArray().size() != entries) {
        fail(resource.resourceId + ".replicated_file_offsets must contain "
            + std::to_string(entries) + " entry lists");
    }

    std::vector<std::vector<std::size_t>> result;
    std::set<std::size_t> seen;
    const std::vector<Value> &lists = raw->asArray();
    for (std::size_t entry = 0; entry < lists.size(); ++entry) {
        const std::string context = resource.resourceId
            + ".replicated_file_offsets[" + std::to_string(entry) + "]";
        if (!lists[entry].isArray() || lists[entry].asArray().empty()) {
            fail(context + " must be a non-empty list");
        }
        std::vector<std::size_t> offsets;
        for (const Value &offset : lists[entry].asArray()) {
            offsets.push_back(requireInteger(&offset, context));
        }
        const std::set<std::size_t> unique(offsets.begin(), offsets.end());
        bool overlaps = unique.size() != offsets.size();
        for (const std::size_t offset : offsets) {
            if (seen.count(offset) != 0) overlaps = true;
        }
        if (overlaps) {
            fail(resource.resourceId
                + ".replicated_file_offsets overlap or repeat");
        }
        seen.insert(offsets.begin(), offsets.end());
        result.push_back(std::move(offsets));
    }
    return result;
}

} // namespace retrolarium::core
