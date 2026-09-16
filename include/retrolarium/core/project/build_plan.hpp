#pragma once

#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace retrolarium::core {

// Raised when a build plan cannot be applied to the source it names.
class BuildPlanError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// One replacement, carrying what it expects to find as well as what it writes.
//
// The expectation is the point: a plan built against one ROM must refuse to
// apply to another, and two resources that write the same byte must agree
// about it rather than race.
struct BuildChange final {
    std::size_t fileOffset = 0;
    std::vector<std::uint8_t> expected;
    std::vector<std::uint8_t> replacement;
    // Which resource produced this, used only in diagnostics.
    std::string resourceId;
};

// Applies every change to `source` and returns the result.
//
// Refuses a source whose SHA-256 is not `sourceSha256`, a change whose
// expected bytes are not what the source holds, and two changes that disagree
// about the same byte. Two changes that agree are fine: a replicated palette
// legitimately writes the same value in several places.
[[nodiscard]] std::vector<std::uint8_t> applyBuildPlan(
    const std::vector<std::uint8_t> &source, const std::string &sourceSha256,
    const std::vector<BuildChange> &changes);

} // namespace retrolarium::core
