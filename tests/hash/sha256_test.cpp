#include <retrolarium/core/hash/sha256.hpp>

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
    const std::string actual = retrolarium::core::sha256Hex(bytesOf(input));
    if (actual != digest) {
        std::cerr << "FAIL: sha256 of " << input.size() << " bytes: got " << actual
                  << ", wanted " << digest << '\n';
        ++failures;
    }
}

} // namespace

int main()
{
    // Published NIST vectors, so the core's digest is verified independently of
    // the Python oracle rather than against another copy of the same code.
    expect("", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    expect("abc",
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    expect("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq",
        "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1");

    // Exercises the padding branch where the length field needs an extra block.
    expect(std::string(55, 'a'),
        "9f4390f8d30c2dd92ec9f095b65e2b9ae9b0a925a5258e241c9f1e910f734318");
    expect(std::string(56, 'a'),
        "b35439a4ac6f0948b6d6f9e3c6af0f5f590ce20f1bde7090ef7970686ec6738a");
    expect(std::string(63, 'a'),
        "7d3e74a05d7db15bce4ad9ec0658ea98e3f06eeecf16b4c6fff2da457ddc2f34");
    expect(std::string(64, 'a'),
        "ffe054fe7ae0cb6dc65c3af9b61d5209f439851db43d0ba5997337df154668eb");
    expect(std::string(1000, 'a'),
        "41edece42d63e8d9bf515a9ba6932e1c20cbc9f5a5d134645adb5db1b9737ea3");

    // Incremental updates must produce the same digest as one-shot hashing.
    {
        retrolarium::core::Sha256 hash;
        const std::string part = "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq";
        for (const char character : part) {
            const auto value = static_cast<std::uint8_t>(character);
            hash.update(&value, 1);
        }
        const std::string actual = hash.hex();
        if (actual
            != "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1") {
            std::cerr << "FAIL: incremental sha256 got " << actual << '\n';
            ++failures;
        }
    }

    if (failures != 0) {
        std::cerr << failures << " sha256 check(s) failed\n";
        return 1;
    }
    std::cout << "sha256 vectors passed\n";
    return 0;
}
