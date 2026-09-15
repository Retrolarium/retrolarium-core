#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace retrolarium::core {

// The core cannot use QCryptographicHash: it must build and run without Qt so
// the same sources can produce both the rlcore executable and the static
// library linked into the Qt application.
class Sha256 final {
public:
    Sha256() noexcept;

    void update(const std::uint8_t *data, std::size_t size) noexcept;
    void update(const std::vector<std::uint8_t> &data) noexcept;

    // Finishes the digest. The object must not be updated afterwards.
    [[nodiscard]] std::string hex();

private:
    void compress(const std::uint8_t block[64]) noexcept;

    std::uint32_t state_[8];
    std::uint8_t buffer_[64];
    std::size_t buffered_ = 0;
    std::uint64_t length_ = 0;
};

[[nodiscard]] std::string sha256Hex(const std::uint8_t *data, std::size_t size);
[[nodiscard]] std::string sha256Hex(const std::vector<std::uint8_t> &data);

} // namespace retrolarium::core
