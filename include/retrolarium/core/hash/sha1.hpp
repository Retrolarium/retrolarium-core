#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace retrolarium::core {

// Profiles record a payload's SHA-1 alongside its SHA-256, so verifying one
// needs both. Same reason as Sha256 for not reaching for QCryptographicHash:
// the core builds and runs without Qt.
class Sha1 final {
public:
    Sha1() noexcept;

    void update(const std::uint8_t *data, std::size_t size) noexcept;
    void update(const std::vector<std::uint8_t> &data) noexcept;

    // Finishes the digest. The object must not be updated afterwards.
    [[nodiscard]] std::string hex();

private:
    void compress(const std::uint8_t block[64]) noexcept;

    std::uint32_t state_[5];
    std::uint8_t buffer_[64];
    std::size_t buffered_ = 0;
    std::uint64_t length_ = 0;
};

[[nodiscard]] std::string sha1Hex(const std::uint8_t *data, std::size_t size);
[[nodiscard]] std::string sha1Hex(const std::vector<std::uint8_t> &data);

} // namespace retrolarium::core
