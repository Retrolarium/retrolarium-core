#include <retrolarium/core/fds.hpp>

#include <algorithm>
#include <set>

namespace retrolarium::core {
namespace {

constexpr std::size_t kSideSize = 65500;
constexpr std::size_t kFileCountBlock = 56;
constexpr std::size_t kHeaderSize = 16;

std::vector<FdsFileRecord> selectedRecords(
    const std::vector<std::uint8_t> &image, const std::vector<int> &recordIds)
{
    const std::set<int> unique(recordIds.begin(), recordIds.end());
    if (recordIds.empty() || unique.size() != recordIds.size()) {
        throw FdsError("FDS payload record IDs must be non-empty and unique");
    }
    const std::vector<FdsFileRecord> records = parseFdsSide(image);
    std::vector<FdsFileRecord> selected;
    for (const int identifier : recordIds) {
        std::size_t matches = 0;
        const FdsFileRecord *found = nullptr;
        for (const FdsFileRecord &record : records) {
            if (record.fileId == identifier) {
                ++matches;
                found = &record;
            }
        }
        if (matches != 1) {
            throw FdsError(
                "FDS file ID is not unique: " + std::to_string(identifier));
        }
        selected.push_back(*found);
    }
    return selected;
}

std::size_t totalSize(const std::vector<FdsFileRecord> &records)
{
    std::size_t total = 0;
    for (const FdsFileRecord &record : records) {
        total += record.size;
    }
    return total;
}

} // namespace

std::vector<FdsFileRecord> parseFdsSide(const std::vector<std::uint8_t> &image)
{
    if (image.size() != kSideSize || image[0] != 1) {
        throw FdsError("FDS image must be one 65500-byte raw disk side");
    }
    std::size_t position = kFileCountBlock;
    if (image[position] != 2) {
        throw FdsError("invalid FDS file-count block");
    }
    const int fileCount = image[position + 1];
    position += 2;

    std::vector<FdsFileRecord> records;
    for (int index = 0; index < fileCount; ++index) {
        const std::size_t headerOffset = position;
        const std::size_t headerEnd = headerOffset + kHeaderSize;
        if (headerEnd > image.size() || image[headerOffset] != 3) {
            throw FdsError(
                "invalid FDS file-header block " + std::to_string(index));
        }
        const std::uint8_t *header = image.data() + headerOffset;
        const std::size_t size =
            static_cast<std::size_t>(header[13]) | static_cast<std::size_t>(header[14]) << 8;
        if (headerEnd >= image.size() || image[headerEnd] != 4) {
            throw FdsError("invalid FDS file-data block " + std::to_string(index));
        }
        const std::size_t dataOffset = headerEnd + 1;
        const std::size_t dataEnd = dataOffset + size;
        if (dataEnd > image.size()) {
            throw FdsError("truncated FDS file-data block " + std::to_string(index));
        }

        FdsFileRecord record;
        record.fileNumber = header[1];
        record.fileId = header[2];
        record.name.assign(header + 3, header + 11);
        record.loadAddress = header[11] | header[12] << 8;
        record.size = size;
        record.fileType = header[15];
        record.headerOffset = headerOffset;
        record.dataOffset = dataOffset;
        records.push_back(std::move(record));
        position = dataEnd;
    }

    // Anything after the declared files has to be blank, so a side cannot hide
    // data the file table does not account for.
    if (std::any_of(image.begin() + static_cast<std::ptrdiff_t>(position),
            image.end(), [](std::uint8_t byte) { return byte != 0; })) {
        throw FdsError("FDS side has nonzero data after its declared files");
    }
    return records;
}

std::vector<std::uint8_t> fdsPayload(
    const std::vector<std::uint8_t> &image, const std::vector<int> &recordIds)
{
    std::vector<std::uint8_t> result;
    for (const FdsFileRecord &record : selectedRecords(image, recordIds)) {
        const auto begin = image.begin() + static_cast<std::ptrdiff_t>(record.dataOffset);
        result.insert(result.end(), begin,
            begin + static_cast<std::ptrdiff_t>(record.size));
    }
    return result;
}

std::vector<FdsPayloadRange> fdsPayloadRanges(
    const std::vector<std::uint8_t> &image, const std::vector<int> &recordIds,
    std::size_t offset, std::size_t size)
{
    const std::vector<FdsFileRecord> selected = selectedRecords(image, recordIds);
    const std::size_t total = totalSize(selected);
    if (size == 0 || offset + size > total) {
        throw FdsError("FDS payload range " + std::to_string(offset) + "+"
            + std::to_string(size) + " exceeds " + std::to_string(total)
            + " bytes");
    }

    std::vector<FdsPayloadRange> result;
    std::size_t logicalStart = 0;
    const std::size_t requestedEnd = offset + size;
    for (const FdsFileRecord &record : selected) {
        const std::size_t logicalEnd = logicalStart + record.size;
        const std::size_t overlapStart = std::max(offset, logicalStart);
        const std::size_t overlapEnd = std::min(requestedEnd, logicalEnd);
        if (overlapStart < overlapEnd) {
            FdsPayloadRange range;
            range.fileOffset = record.dataOffset + overlapStart - logicalStart;
            range.payloadOffset = overlapStart - offset;
            range.size = overlapEnd - overlapStart;
            result.push_back(range);
        }
        logicalStart = logicalEnd;
    }
    return result;
}

std::vector<std::uint8_t> replaceFdsPayload(
    const std::vector<std::uint8_t> &image, const std::vector<int> &recordIds,
    const std::vector<std::uint8_t> &payload)
{
    const std::vector<FdsFileRecord> selected = selectedRecords(image, recordIds);
    const std::size_t expected = totalSize(selected);
    if (payload.size() != expected) {
        throw FdsError("FDS replacement payload is " + std::to_string(payload.size())
            + " bytes, expected " + std::to_string(expected));
    }

    std::vector<std::uint8_t> result = image;
    std::size_t position = 0;
    for (const FdsFileRecord &record : selected) {
        std::copy(payload.begin() + static_cast<std::ptrdiff_t>(position),
            payload.begin() + static_cast<std::ptrdiff_t>(position + record.size),
            result.begin() + static_cast<std::ptrdiff_t>(record.dataOffset));
        position += record.size;
    }
    return result;
}

} // namespace retrolarium::core
