#include <retrolarium/core/build_plan.hpp>

#include <retrolarium/core/sha256.hpp>

#include <map>

namespace retrolarium::core {
namespace {

std::string hexOffset(std::size_t value)
{
    static constexpr char kDigits[] = "0123456789ABCDEF";
    if (value == 0) return "0";
    std::string out;
    while (value != 0) {
        out.insert(out.begin(), kDigits[value & 0xF]);
        value >>= 4;
    }
    return out;
}

} // namespace

std::vector<std::uint8_t> applyBuildPlan(
    const std::vector<std::uint8_t> &source, const std::string &sourceSha256,
    const std::vector<BuildChange> &changes)
{
    // The plan's own well-formedness comes first: the Kit validates it when
    // the plan is constructed, before it ever sees a source image.
    bool wellFormed = sourceSha256.size() == 64;
    for (const char digit : sourceSha256) {
        const bool hex = (digit >= '0' && digit <= '9')
            || (digit >= 'a' && digit <= 'f');
        if (!hex) wellFormed = false;
    }
    if (!wellFormed) {
        throw BuildPlanError("build plan source_sha256 must be lowercase SHA-256");
    }

    const std::string actualSha = sha256Hex(source);
    if (actualSha != sourceSha256) {
        throw BuildPlanError("build plan source SHA-256 is " + actualSha
            + ", expected " + sourceSha256);
    }

    // Collected per byte rather than applied in order, so a disagreement is
    // found before anything is written.
    std::map<std::size_t, std::pair<std::uint8_t, std::uint8_t>> pending;
    for (const BuildChange &change : changes) {
        if (change.expected.empty()) {
            throw BuildPlanError("address range size must be positive");
        }
        if (change.expected.size() != change.replacement.size()) {
            throw BuildPlanError(
                "change payload sizes must match the declared span");
        }
        if (change.fileOffset > source.size()
            || source.size() - change.fileOffset < change.expected.size()) {
            throw BuildPlanError("build change at file:0x"
                + hexOffset(change.fileOffset) + " leaves the source image");
        }
        for (std::size_t index = 0; index < change.expected.size(); ++index) {
            const std::size_t position = change.fileOffset + index;
            if (source[position] != change.expected[index]) {
                throw BuildPlanError("stale change at file:0x"
                    + hexOffset(change.fileOffset)
                    + ": source bytes differ from the plan");
            }
            const auto found = pending.find(position);
            if (found != pending.end()
                && (found->second.first != change.expected[index]
                    || found->second.second != change.replacement[index])) {
                throw BuildPlanError("conflicting build changes at file:0x"
                    + hexOffset(position));
            }
            pending[position] = {change.expected[index], change.replacement[index]};
        }
    }

    std::vector<std::uint8_t> output = source;
    for (const auto &entry : pending) {
        output[entry.first] = entry.second.second;
    }
    return output;
}

} // namespace retrolarium::core
