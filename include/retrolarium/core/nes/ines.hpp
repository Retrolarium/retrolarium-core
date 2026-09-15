#pragma once

#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace retrolarium::core {

// Raised when the input is not an iNES image the pipeline supports. Mirrors
// retrolarium_kit.ines.InesError.
class InesError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

struct ImageRegion final {
    std::string name;
    std::size_t fileOffset = 0;
    std::size_t size = 0;
    std::string sha256;
};

enum class Mirroring { Horizontal, Vertical, FourScreen };

[[nodiscard]] std::string mirroringName(Mirroring mirroring);

struct InesImage final {
    std::vector<std::uint8_t> data;
    std::vector<std::uint8_t> header;
    std::vector<std::uint8_t> trainer;
    std::vector<std::uint8_t> prg;
    std::vector<std::uint8_t> chr;
    int mapper = 0;
    Mirroring mirroring = Mirroring::Horizontal;
    bool battery = false;
    std::string sha256;

    [[nodiscard]] std::vector<ImageRegion> regions() const;
};

// Size the header declares, including the header itself. Throws InesError for
// a missing magic, a NES 2.0 image or a zero PRG count.
[[nodiscard]] std::size_t declaredInesSize(const std::vector<std::uint8_t> &data);

// Parses a whole image. The size must match the declaration exactly.
[[nodiscard]] InesImage parseInes(std::vector<std::uint8_t> data);

// Parses an iNES image embedded at the start of a larger container and returns
// the image together with the trailing bytes.
[[nodiscard]] std::pair<InesImage, std::vector<std::uint8_t>> parseInesPrefix(
    const std::vector<std::uint8_t> &data);

[[nodiscard]] InesImage loadInes(const std::string &path);

} // namespace retrolarium::core
