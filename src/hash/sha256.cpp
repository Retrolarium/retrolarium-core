#include <retrolarium/core/hash/sha256.hpp>

#include <algorithm>
#include <cstring>

namespace retrolarium::core {
namespace {

constexpr std::uint32_t kRoundConstants[64] {
    0x428a2f98u, 0x71374491u, 0xb5c0fbcfu, 0xe9b5dba5u,
    0x3956c25bu, 0x59f111f1u, 0x923f82a4u, 0xab1c5ed5u,
    0xd807aa98u, 0x12835b01u, 0x243185beu, 0x550c7dc3u,
    0x72be5d74u, 0x80deb1feu, 0x9bdc06a7u, 0xc19bf174u,
    0xe49b69c1u, 0xefbe4786u, 0x0fc19dc6u, 0x240ca1ccu,
    0x2de92c6fu, 0x4a7484aau, 0x5cb0a9dcu, 0x76f988dau,
    0x983e5152u, 0xa831c66du, 0xb00327c8u, 0xbf597fc7u,
    0xc6e00bf3u, 0xd5a79147u, 0x06ca6351u, 0x14292967u,
    0x27b70a85u, 0x2e1b2138u, 0x4d2c6dfcu, 0x53380d13u,
    0x650a7354u, 0x766a0abbu, 0x81c2c92eu, 0x92722c85u,
    0xa2bfe8a1u, 0xa81a664bu, 0xc24b8b70u, 0xc76c51a3u,
    0xd192e819u, 0xd6990624u, 0xf40e3585u, 0x106aa070u,
    0x19a4c116u, 0x1e376c08u, 0x2748774cu, 0x34b0bcb5u,
    0x391c0cb3u, 0x4ed8aa4au, 0x5b9cca4fu, 0x682e6ff3u,
    0x748f82eeu, 0x78a5636fu, 0x84c87814u, 0x8cc70208u,
    0x90befffau, 0xa4506cebu, 0xbef9a3f7u, 0xc67178f2u,
};

constexpr std::uint32_t rotateRight(std::uint32_t value, int bits) noexcept
{
    return (value >> bits) | (value << (32 - bits));
}

} // namespace

Sha256::Sha256() noexcept
    : state_ {0x6a09e667u, 0xbb67ae85u, 0x3c6ef372u, 0xa54ff53au,
          0x510e527fu, 0x9b05688cu, 0x1f83d9abu, 0x5be0cd19u}
    , buffer_ {}
{
}

void Sha256::compress(const std::uint8_t block[64]) noexcept
{
    std::uint32_t words[64];
    for (int index = 0; index < 16; ++index) {
        words[index] = static_cast<std::uint32_t>(block[index * 4]) << 24
            | static_cast<std::uint32_t>(block[index * 4 + 1]) << 16
            | static_cast<std::uint32_t>(block[index * 4 + 2]) << 8
            | static_cast<std::uint32_t>(block[index * 4 + 3]);
    }
    for (int index = 16; index < 64; ++index) {
        const std::uint32_t previous = words[index - 15];
        const std::uint32_t ahead = words[index - 2];
        const std::uint32_t s0 = rotateRight(previous, 7) ^ rotateRight(previous, 18)
            ^ (previous >> 3);
        const std::uint32_t s1 = rotateRight(ahead, 17) ^ rotateRight(ahead, 19)
            ^ (ahead >> 10);
        words[index] = words[index - 16] + s0 + words[index - 7] + s1;
    }

    std::uint32_t a = state_[0];
    std::uint32_t b = state_[1];
    std::uint32_t c = state_[2];
    std::uint32_t d = state_[3];
    std::uint32_t e = state_[4];
    std::uint32_t f = state_[5];
    std::uint32_t g = state_[6];
    std::uint32_t h = state_[7];

    for (int index = 0; index < 64; ++index) {
        const std::uint32_t s1 = rotateRight(e, 6) ^ rotateRight(e, 11)
            ^ rotateRight(e, 25);
        const std::uint32_t choose = (e & f) ^ (~e & g);
        const std::uint32_t temp1 = h + s1 + choose + kRoundConstants[index]
            + words[index];
        const std::uint32_t s0 = rotateRight(a, 2) ^ rotateRight(a, 13)
            ^ rotateRight(a, 22);
        const std::uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
        const std::uint32_t temp2 = s0 + majority;

        h = g;
        g = f;
        f = e;
        e = d + temp1;
        d = c;
        c = b;
        b = a;
        a = temp1 + temp2;
    }

    state_[0] += a;
    state_[1] += b;
    state_[2] += c;
    state_[3] += d;
    state_[4] += e;
    state_[5] += f;
    state_[6] += g;
    state_[7] += h;
}

void Sha256::update(const std::uint8_t *data, std::size_t size) noexcept
{
    length_ += static_cast<std::uint64_t>(size);
    while (size > 0) {
        const std::size_t take = std::min(size, std::size_t {64} - buffered_);
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

void Sha256::update(const std::vector<std::uint8_t> &data) noexcept
{
    update(data.data(), data.size());
}

std::string Sha256::hex()
{
    const std::uint64_t bits = length_ * 8;

    // update() compresses as soon as the buffer fills, so buffered_ is always
    // below 64 here and the padding byte always fits.
    buffer_[buffered_++] = 0x80;
    if (buffered_ > 56) {
        std::memset(buffer_ + buffered_, 0, 64 - buffered_);
        compress(buffer_);
        buffered_ = 0;
    }
    std::memset(buffer_ + buffered_, 0, 56 - buffered_);
    for (int index = 0; index < 8; ++index) {
        buffer_[56 + index] =
            static_cast<std::uint8_t>((bits >> (56 - index * 8)) & 0xFF);
    }
    compress(buffer_);
    buffered_ = 0;

    static constexpr char kDigits[] = "0123456789abcdef";
    std::string result;
    result.reserve(64);
    for (const std::uint32_t word : state_) {
        for (int shift = 28; shift >= 0; shift -= 4) {
            result.push_back(kDigits[(word >> shift) & 0xF]);
        }
    }
    return result;
}

std::string sha256Hex(const std::uint8_t *data, std::size_t size)
{
    Sha256 hash;
    hash.update(data, size);
    return hash.hex();
}

std::string sha256Hex(const std::vector<std::uint8_t> &data)
{
    return sha256Hex(data.data(), data.size());
}

} // namespace retrolarium::core
