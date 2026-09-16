#pragma once

#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace retrolarium::core {

// Raised when the input is not a supported raw FDS side.
class FdsError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

struct FdsFileRecord final {
    int fileNumber = 0;
    int fileId = 0;
    // Eight raw bytes, not text: the field is not required to be printable.
    std::vector<std::uint8_t> name;
    int loadAddress = 0;
    std::size_t size = 0;
    int fileType = 0;
    std::size_t headerOffset = 0;
    std::size_t dataOffset = 0;
};

// Where one slice of a logical payload lives inside the side.
struct FdsPayloadRange final {
    std::size_t fileOffset = 0;
    std::size_t payloadOffset = 0;
    std::size_t size = 0;
};

[[nodiscard]] std::vector<FdsFileRecord> parseFdsSide(
    const std::vector<std::uint8_t> &image);

// Concatenates the named files in the order asked for, which is what makes a
// payload spanning several files addressable as one range.
[[nodiscard]] std::vector<std::uint8_t> fdsPayload(
    const std::vector<std::uint8_t> &image, const std::vector<int> &recordIds);

[[nodiscard]] std::vector<FdsPayloadRange> fdsPayloadRanges(
    const std::vector<std::uint8_t> &image, const std::vector<int> &recordIds,
    std::size_t offset, std::size_t size);

[[nodiscard]] std::vector<std::uint8_t> replaceFdsPayload(
    const std::vector<std::uint8_t> &image, const std::vector<int> &recordIds,
    const std::vector<std::uint8_t> &payload);

} // namespace retrolarium::core
