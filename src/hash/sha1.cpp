#include <retrolarium/core/sha1.hpp>

#include <cstring>

namespace retrolarium::core {
namespace {

std::uint32_t rotateLeft(std::uint32_t value, int amount) noexcept
{
    return (value << amount) | (value >> (32 - amount));
}

} // namespace

Sha1::Sha1() noexcept
    : state_ {0x67452301u, 0xEFCDAB89u, 0x98BADCFEu, 0x10325476u, 0xC3D2E1F0u}
    , buffer_ {}
{
}

void Sha1::compress(const std::uint8_t block[64]) noexcept
{
    std::uint32_t words[80];
    for (int index = 0; index < 16; ++index) {
        words[index] = static_cast<std::uint32_t>(block[index * 4]) << 24
            | static_cast<std::uint32_t>(block[index * 4 + 1]) << 16
            | static_cast<std::uint32_t>(block[index * 4 + 2]) << 8
            | static_cast<std::uint32_t>(block[index * 4 + 3]);
    }
    for (int index = 16; index < 80; ++index) {
        words[index] = rotateLeft(words[index - 3] ^ words[index - 8]
                ^ words[index - 14] ^ words[index - 16],
            1);
    }

    std::uint32_t a = state_[0];
    std::uint32_t b = state_[1];
    std::uint32_t c = state_[2];
    std::uint32_t d = state_[3];
    std::uint32_t e = state_[4];

    for (int index = 0; index < 80; ++index) {
        std::uint32_t f = 0;
        std::uint32_t k = 0;
        if (index < 20) {
            f = (b & c) | (~b & d);
            k = 0x5A827999u;
        } else if (index < 40) {
            f = b ^ c ^ d;
            k = 0x6ED9EBA1u;
        } else if (index < 60) {
            f = (b & c) | (b & d) | (c & d);
            k = 0x8F1BBCDCu;
        } else {
            f = b ^ c ^ d;
            k = 0xCA62C1D6u;
        }
        const std::uint32_t next = rotateLeft(a, 5) + f + e + k + words[index];
        e = d;
        d = c;
        c = rotateLeft(b, 30);
        b = a;
        a = next;
    }

    state_[0] += a;
    state_[1] += b;
    state_[2] += c;
    state_[3] += d;
    state_[4] += e;
}

void Sha1::update(const std::uint8_t *data, std::size_t size) noexcept
{
    length_ += static_cast<std::uint64_t>(size);
    while (size > 0) {
        const std::size_t room = 64 - buffered_;
        const std::size_t take = size < room ? size : room;
        std::memcpy(buffer_ + buffered_, data, take);
        buffered_ += take;
        data += take;
        size -= take;
        if (buffered_ == 64) {
            compress(buffer_);
            buffered_ = 0;
        }
    }
}

void Sha1::update(const std::vector<std::uint8_t> &data) noexcept
{
    update(data.data(), data.size());
}

std::string Sha1::hex()
{
    const std::uint64_t bits = length_ * 8;
    const std::uint8_t padding = 0x80;
    update(&padding, 1);
    const std::uint8_t zero = 0;
    while (buffered_ != 56) {
        update(&zero, 1);
    }
    std::uint8_t tail[8];
    for (int index = 0; index < 8; ++index) {
        tail[index] = static_cast<std::uint8_t>((bits >> (56 - index * 8)) & 0xFF);
    }
    update(tail, 8);

    static constexpr char kDigits[] = "0123456789abcdef";
    std::string out;
    out.reserve(40);
    for (const std::uint32_t word : state_) {
        for (int shift = 28; shift >= 0; shift -= 4) {
            out.push_back(kDigits[(word >> shift) & 0xF]);
        }
    }
    return out;
}

std::string sha1Hex(const std::uint8_t *data, std::size_t size)
{
    Sha1 digest;
    digest.update(data, size);
    return digest.hex();
}

std::string sha1Hex(const std::vector<std::uint8_t> &data)
{
    return sha1Hex(data.data(), data.size());
}

} // namespace retrolarium::core
