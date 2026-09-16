#include <retrolarium/core/sha1.hpp>

#include <cstdint>
#include <iostream>
#include <string>
#include <vector>

namespace {

int failures = 0;

std::vector<std::uint8_t> bytesOf(const std::string &text)
{
    return {text.begin(), text.end()};
}

void expect(const std::string &input, const std::string &digest)
{
    const std::string actual = retrolarium::core::sha1Hex(bytesOf(input));
    if (actual != digest) {
        std::cerr << "FAIL: sha1 of " << input.size() << " bytes: got " << actual
                  << ", wanted " << digest << '\n';
        ++failures;
    }
}

} // namespace

int main()
{
    // Published RFC 3174 and NIST vectors, so the digest is verified against
    // the standard rather than against another copy of this code.
    expect("", "da39a3ee5e6b4b0d3255bfef95601890afd80709");
    expect("abc", "a9993e364706816aba3e25717850c26c9cd0d89d");
    expect("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq",
        "84983e441c3bd26ebaae4aa1f95129e5e54670f1");
    expect(std::string(1000000, 'a'),
        "34aa973cd4c4daa4f61eeb2bdbad27316534016f");

    // The three padding branches: one where the length still fits the block,
    // one where it needs a whole extra block, and the boundary between them.
    expect(std::string(55, 'a'), "c1c8bbdc22796e28c0e15163d20899b65621d65a");
    expect(std::string(56, 'a'), "c2db330f6083854c99d4b5bfb6e8f29f201be699");
    expect(std::string(64, 'a'), "0098ba824b5c16427bd7a1122a5a442a25ec644d");

    // Feeding the same bytes in pieces must not change the digest, because a
    // payload is hashed as it is read.
    {
        retrolarium::core::Sha1 digest;
        const std::string first = "abcdbcdecdefdefgefghfghighijhijk";
        const std::string second = "ijkljklmklmnlmnomnopnopq";
        digest.update(bytesOf(first));
        digest.update(bytesOf(second));
        const std::string actual = digest.hex();
        if (actual != "84983e441c3bd26ebaae4aa1f95129e5e54670f1") {
            std::cerr << "FAIL: split update gave " << actual << '\n';
            ++failures;
        }
    }

    if (failures != 0) {
        std::cerr << failures << " sha1 vector(s) failed\n";
        return 1;
    }
    std::cout << "sha1 vectors passed\n";
    return 0;
}
