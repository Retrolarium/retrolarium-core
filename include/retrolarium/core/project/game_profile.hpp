#pragma once

#include <retrolarium/core/value.hpp>

#include <cstdint>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace retrolarium::core {

// Raised when a game profile violates its schema. The message matches the
// Kit's AuthoringError text, so both loaders can be compared on more than
// whether they failed.
class AuthoringError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// ^[a-z0-9][a-z0-9._-]*$ - note this is not the rule Studio projects use for
// their identifiers, which requires a leading letter.
[[nodiscard]] bool isStableIdentifier(const std::string &value);

struct ResourceSpec final {
    std::string resourceId;
    std::string kind;
    std::string codec;
    std::string capacityPolicy;
    // Shape belongs to the codec, so the profile only carries it through.
    std::map<std::string, Value> parameters;
    bool hasPayload = false;
    std::string payload;
};

struct ResourceOverrideSpec final {
    std::string resourceId;
    std::map<std::string, Value> parameters;
    bool hasPayload = false;
    std::string payload;
};

struct PayloadSpec final {
    std::string payloadId;
    // "range" or "fds-records"; the two are mutually exclusive in what else
    // the record may carry.
    std::string storage;
    std::int64_t size = 0;
    std::string sha1;
    bool hasFileOffset = false;
    std::int64_t fileOffset = 0;
    std::vector<std::int64_t> recordIds;
    bool hasLoadAddress = false;
    std::int64_t loadAddress = 0;
};

struct RevisionSpec final {
    std::string revisionId;
    std::string name;
    std::int64_t size = 0;
    std::string sha1;
    std::string sha256;
    std::string container;
    bool hasMapper = false;
    std::int64_t mapper = 0;
    // A revision either replaces the profile's resource list outright or
    // overrides entries in it, never both.
    bool hasCapabilities = false;
    std::vector<std::string> capabilities;
    bool hasResources = false;
    std::vector<ResourceSpec> resources;
    std::vector<ResourceOverrideSpec> resourceOverrides;
    std::vector<PayloadSpec> payloads;
};

struct GameProfile final {
    std::string gameId;
    std::int64_t profileVersion = 0;
    std::string name;
    std::string platform;
    std::vector<std::string> capabilities;
    std::vector<RevisionSpec> revisions;
    std::vector<ResourceSpec> resources;

    [[nodiscard]] const RevisionSpec &revision(const std::string &revisionId) const;
    // The resource list as the revision sees it: its own list, or the
    // profile's with the revision's overrides merged in.
    [[nodiscard]] std::vector<ResourceSpec> resourcesFor(
        const RevisionSpec &revision) const;
    [[nodiscard]] const PayloadSpec &payload(
        const RevisionSpec &revision, const std::string &payloadId) const;
};

[[nodiscard]] GameProfile parseGameProfile(const std::string &json);
[[nodiscard]] GameProfile loadGameProfile(const std::string &path);

// Renders the profile the way the corpus generator prints it, so the two
// loaders can be compared byte for byte.
[[nodiscard]] std::string renderGameProfile(const GameProfile &profile);

} // namespace retrolarium::core
