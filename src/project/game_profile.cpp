#include <retrolarium/core/project/game_profile.hpp>

#include <nlohmann/json.hpp>

#include <algorithm>
#include <fstream>
#include <set>

namespace retrolarium::core {
namespace {

using Json = nlohmann::json;

constexpr const char *kProfileSchema = "retrolarium.game-profile";
constexpr int kProfileSchemaVersion = 1;

[[noreturn]] void fail(const std::string &message)
{
    throw AuthoringError(message);
}

const Json *member(const Json &object, const char *name)
{
    const auto found = object.find(name);
    return found == object.end() ? nullptr : &*found;
}

const Json &requireObject(const Json *value, const std::string &name)
{
    if (value == nullptr || !value->is_object()) {
        fail(name + " must be an object");
    }
    return *value;
}

std::string requireString(const Json *value, const std::string &name)
{
    if (value == nullptr || !value->is_string()
        || value->get<std::string>().empty()) {
        fail(name + " must be a non-empty string");
    }
    return value->get<std::string>();
}

// Mirrors stable_identifier, whose message quotes the offending value the way
// Python's repr does.
std::string quoted(const Json *value)
{
    if (value == nullptr) return "None";
    if (value->is_string()) return "'" + value->get<std::string>() + "'";
    if (value->is_boolean()) return value->get<bool>() ? "True" : "False";
    if (value->is_null()) return "None";
    return value->dump();
}

std::string stableIdentifier(const Json *value, const std::string &fieldName)
{
    if (value == nullptr || !value->is_string()
        || !isStableIdentifier(value->get<std::string>())) {
        fail(fieldName + " is not a stable identifier: " + quoted(value));
    }
    return value->get<std::string>();
}

bool isLowercaseHex(const std::string &value, std::size_t length)
{
    if (value.size() != length) return false;
    return std::all_of(value.begin(), value.end(), [](char character) {
        return (character >= '0' && character <= '9')
            || (character >= 'a' && character <= 'f');
    });
}

// Python distinguishes bool from int; JSON does too, so an integer field has
// to reject a boolean explicitly.
bool isInteger(const Json *value)
{
    return value != nullptr && value->is_number_integer() && !value->is_boolean();
}

std::map<std::string, Value> parameters(const Json &item, const std::string &name)
{
    const Json *raw = member(item, "parameters");
    if (raw == nullptr) return {};
    if (!raw->is_object()) {
        fail(name + ".parameters must be an object");
    }
    std::map<std::string, Value> result;
    for (auto entry = raw->begin(); entry != raw->end(); ++entry) {
        result.emplace(entry.key(), parseValue(entry.value().dump()));
    }
    return result;
}

std::vector<std::string> capabilities(const Json *value, const std::string &name)
{
    if (value == nullptr || !value->is_array()) {
        fail(name + " must be a string array");
    }
    std::vector<std::string> result;
    for (const Json &item : *value) {
        if (!item.is_string()) {
            fail(name + " must be a string array");
        }
        result.push_back(item.get<std::string>());
    }
    return result;
}

void checkUniqueCapabilities(
    const std::vector<std::string> &values, const char *what, const char *field)
{
    const std::set<std::string> unique(values.begin(), values.end());
    if (unique.size() != values.size()) {
        fail(std::string(what) + " capabilities must be unique");
    }
    for (const std::string &value : values) {
        if (!isStableIdentifier(value)) {
            fail(std::string(field) + " is not a stable identifier: '" + value + "'");
        }
    }
}

ResourceSpec resourceSpec(const Json &item, const std::string &name)
{
    // Two phases, in the Kit's order: every field is read and type-checked
    // first, then the identifier rules run. A profile that breaks both has to
    // be reported by the same field on each side.
    ResourceSpec spec;
    spec.parameters = parameters(item, name);
    spec.resourceId = requireString(member(item, "id"), name + ".id");
    spec.kind = requireString(member(item, "kind"), name + ".kind");
    spec.codec = requireString(member(item, "codec"), name + ".codec");
    spec.capacityPolicy = requireString(
        member(item, "capacity_policy"), name + ".capacity_policy");
    const Json *payload = member(item, "payload");
    if (payload != nullptr) {
        spec.hasPayload = true;
        spec.payload = requireString(payload, name + ".payload");
    }

    static_cast<void>(stableIdentifier(member(item, "id"), "resource id"));
    static_cast<void>(stableIdentifier(member(item, "kind"), "resource kind"));
    static_cast<void>(stableIdentifier(member(item, "codec"), "codec id"));
    static_cast<void>(stableIdentifier(
        member(item, "capacity_policy"), "capacity policy"));
    if (spec.hasPayload) {
        static_cast<void>(stableIdentifier(payload, "resource payload"));
    }
    return spec;
}

std::vector<ResourceSpec> resourceSpecs(const Json *value, const std::string &name)
{
    if (value == nullptr || !value->is_array() || value->empty()) {
        fail(name + " must be a non-empty array");
    }
    std::vector<ResourceSpec> specs;
    for (std::size_t index = 0; index < value->size(); ++index) {
        const std::string itemName = name + "[" + std::to_string(index) + "]";
        const Json &item = requireObject(&(*value)[index], itemName);
        specs.push_back(resourceSpec(item, itemName));
    }
    return specs;
}

std::vector<ResourceOverrideSpec> resourceOverrides(
    const Json *value, const std::string &name)
{
    if (value == nullptr) return {};
    if (!value->is_array()) {
        fail(name + " must be an array");
    }
    std::vector<ResourceOverrideSpec> overrides;
    for (std::size_t index = 0; index < value->size(); ++index) {
        const std::string itemName = name + "[" + std::to_string(index) + "]";
        const Json &item = requireObject(&(*value)[index], itemName);
        ResourceOverrideSpec spec;
        spec.resourceId = requireString(member(item, "id"), itemName + ".id");
        spec.parameters = parameters(item, itemName);
        const Json *payload = member(item, "payload");
        if (payload != nullptr) {
            spec.hasPayload = true;
            spec.payload = requireString(payload, itemName + ".payload");
        }
        static_cast<void>(
            stableIdentifier(member(item, "id"), "resource override id"));
        if (spec.hasPayload) {
            static_cast<void>(
                stableIdentifier(payload, "resource override payload"));
        }
        overrides.push_back(std::move(spec));
    }
    return overrides;
}

std::vector<PayloadSpec> payloadSpecs(const Json *value, const std::string &name)
{
    if (value == nullptr) return {};
    if (!value->is_array()) {
        fail(name + " must be an array");
    }
    std::vector<PayloadSpec> payloads;
    for (std::size_t index = 0; index < value->size(); ++index) {
        const std::string itemName = name + "[" + std::to_string(index) + "]";
        const Json &item = requireObject(&(*value)[index], itemName);
        const Json *recordIds = member(item, "record_ids");
        if (recordIds != nullptr && !recordIds->is_array()) {
            fail(itemName + ".record_ids must be an array");
        }

        PayloadSpec spec;
        spec.payloadId = requireString(member(item, "id"), itemName + ".id");
        spec.storage = requireString(
            member(item, "storage"), itemName + ".storage");
        spec.sha1 = requireString(member(item, "sha1"), itemName + ".sha1");

        static_cast<void>(stableIdentifier(member(item, "id"), "payload id"));
        static_cast<void>(
            stableIdentifier(member(item, "storage"), "payload storage"));
        const Json *size = member(item, "size");
        if (!isInteger(size) || size->get<std::int64_t>() <= 0) {
            fail("payload size must be a positive integer");
        }
        spec.size = size->get<std::int64_t>();
        if (!isLowercaseHex(spec.sha1, 40)) {
            fail("payload sha1 must be lowercase SHA-1");
        }
        const Json *fileOffset = member(item, "file_offset");
        if (fileOffset != nullptr && !fileOffset->is_null()) {
            spec.hasFileOffset = true;
            // Left as -1 when it is not an integer at all, so the storage
            // rules below report it the way the Kit does.
            spec.fileOffset = isInteger(fileOffset)
                ? fileOffset->get<std::int64_t>() : -1;
        }
        if (recordIds != nullptr) {
            for (const Json &record : *recordIds) {
                spec.recordIds.push_back(
                    isInteger(&record) ? record.get<std::int64_t>() : -1);
            }
        }

        if (spec.storage == "range") {
            if (!spec.hasFileOffset || spec.fileOffset < 0
                || !spec.recordIds.empty()) {
                fail("range payload needs a non-negative file offset and no "
                     "record IDs");
            }
        } else if (spec.storage == "fds-records") {
            const std::set<std::int64_t> unique(
                spec.recordIds.begin(), spec.recordIds.end());
            const bool outOfRange = std::any_of(spec.recordIds.begin(),
                spec.recordIds.end(),
                [](std::int64_t record) { return record < 0 || record > 0xFF; });
            if (spec.hasFileOffset || spec.recordIds.empty() || outOfRange
                || unique.size() != spec.recordIds.size()) {
                fail("FDS payload needs unique byte record IDs and no file offset");
            }
        } else {
            fail("unsupported payload storage '" + spec.storage + "'");
        }

        const Json *loadAddress = member(item, "load_address");
        if (loadAddress != nullptr && !loadAddress->is_null()) {
            spec.hasLoadAddress = true;
            if (!isInteger(loadAddress) || loadAddress->get<std::int64_t>() < 0
                || loadAddress->get<std::int64_t>() > 0xFFFF) {
                fail("payload load address must be a 16-bit integer");
            }
            spec.loadAddress = loadAddress->get<std::int64_t>();
        }
        payloads.push_back(std::move(spec));
    }
    return payloads;
}

template <typename T, typename Extract>
void checkUniqueIds(const std::vector<T> &values, Extract extract,
    const std::string &message)
{
    std::set<std::string> unique;
    for (const T &value : values) {
        unique.insert(extract(value));
    }
    if (unique.size() != values.size()) {
        fail(message);
    }
}

} // namespace

bool isStableIdentifier(const std::string &value)
{
    if (value.empty()) return false;
    const char first = value.front();
    const bool firstOk = (first >= 'a' && first <= 'z')
        || (first >= '0' && first <= '9');
    if (!firstOk) return false;
    return std::all_of(value.begin() + 1, value.end(), [](char character) {
        return (character >= 'a' && character <= 'z')
            || (character >= '0' && character <= '9')
            || character == '.' || character == '_' || character == '-';
    });
}

const RevisionSpec &GameProfile::revision(const std::string &revisionId) const
{
    for (const RevisionSpec &candidate : revisions) {
        if (candidate.revisionId == revisionId) return candidate;
    }
    fail("unknown revision '" + revisionId + "'");
}

std::vector<ResourceSpec> GameProfile::resourcesFor(
    const RevisionSpec &selected) const
{
    if (selected.hasResources) return selected.resources;
    if (selected.resourceOverrides.empty()) return resources;

    std::map<std::string, const ResourceOverrideSpec *> overrides;
    for (const ResourceOverrideSpec &override : selected.resourceOverrides) {
        overrides[override.resourceId] = &override;
    }
    std::set<std::string> known;
    for (const ResourceSpec &resource : resources) {
        known.insert(resource.resourceId);
    }
    for (const auto &entry : overrides) {
        if (known.count(entry.first) == 0) {
            // Sorted, so the reported id is the one the Kit reports.
            fail("revision " + selected.revisionId + " overrides unknown resource '"
                + entry.first + "'");
        }
    }

    std::vector<ResourceSpec> merged;
    merged.reserve(resources.size());
    for (const ResourceSpec &resource : resources) {
        const auto found = overrides.find(resource.resourceId);
        if (found == overrides.end()) {
            merged.push_back(resource);
            continue;
        }
        ResourceSpec copy = resource;
        for (const auto &entry : found->second->parameters) {
            copy.parameters[entry.first] = entry.second;
        }
        if (found->second->hasPayload) {
            copy.hasPayload = true;
            copy.payload = found->second->payload;
        }
        merged.push_back(std::move(copy));
    }
    return merged;
}

const PayloadSpec &GameProfile::payload(
    const RevisionSpec &revision, const std::string &payloadId) const
{
    std::size_t matches = 0;
    const PayloadSpec *found = nullptr;
    for (const PayloadSpec &candidate : revision.payloads) {
        if (candidate.payloadId == payloadId) {
            ++matches;
            found = &candidate;
        }
    }
    if (matches != 1) {
        fail("unknown payload '" + payloadId + "' in " + gameId + "/"
            + revision.revisionId);
    }
    return *found;
}

GameProfile parseGameProfile(const std::string &json)
{
    Json document;
    try {
        document = Json::parse(json);
    } catch (const Json::exception &error) {
        fail(std::string("game profile is not valid JSON: ") + error.what());
    }
    if (!document.is_object()) {
        fail("game profile must be an object");
    }

    const Json *schema = member(document, "schema");
    if (schema == nullptr || !schema->is_string()
        || schema->get<std::string>() != kProfileSchema) {
        fail("unsupported game-profile schema");
    }
    const Json *schemaVersion = member(document, "schema_version");
    if (!isInteger(schemaVersion)
        || schemaVersion->get<std::int64_t>() != kProfileSchemaVersion) {
        fail("unsupported game-profile schema version");
    }

    const Json *revisionsValue = member(document, "revisions");
    if (revisionsValue == nullptr || !revisionsValue->is_array()
        || revisionsValue->empty()) {
        fail("game profile revisions must be a non-empty array");
    }

    GameProfile profile;
    profile.capabilities = capabilities(
        member(document, "capabilities"), "game profile capabilities");
    profile.resources = resourceSpecs(member(document, "resources"), "resources");

    for (std::size_t index = 0; index < revisionsValue->size(); ++index) {
        const std::string name = "revisions[" + std::to_string(index) + "]";
        const Json &item = requireObject(&(*revisionsValue)[index], name);

        // Same two phases as a resource, and in the Kit's order the nested
        // lists are built before the revision's own fields are read.
        RevisionSpec revision;
        if (member(item, "capabilities") != nullptr) {
            revision.hasCapabilities = true;
            revision.capabilities = capabilities(
                member(item, "capabilities"), name + ".capabilities");
        }
        if (member(item, "resources") != nullptr) {
            revision.hasResources = true;
            revision.resources = resourceSpecs(
                member(item, "resources"), name + ".resources");
        }
        revision.resourceOverrides = resourceOverrides(
            member(item, "resource_overrides"), name + ".resource_overrides");
        revision.payloads = payloadSpecs(
            member(item, "payloads"), name + ".payloads");

        revision.revisionId = requireString(member(item, "id"), name + ".id");
        revision.name = requireString(member(item, "name"), name + ".name");
        revision.sha1 = requireString(member(item, "sha1"), name + ".sha1");
        revision.sha256 = requireString(member(item, "sha256"), name + ".sha256");
        revision.container = requireString(
            member(item, "container"), name + ".container");

        static_cast<void>(stableIdentifier(member(item, "id"), "revision id"));
        const Json *size = member(item, "size");
        if (!isInteger(size) || size->get<std::int64_t>() <= 0) {
            fail("revision size must be positive");
        }
        revision.size = size->get<std::int64_t>();
        if (!isLowercaseHex(revision.sha1, 40)) {
            fail("revision sha1 must be lowercase SHA-1");
        }
        if (!isLowercaseHex(revision.sha256, 64)) {
            fail("revision sha256 must be lowercase SHA-256");
        }
        static_cast<void>(
            stableIdentifier(member(item, "container"), "revision container"));
        const Json *mapper = member(item, "mapper");
        if (mapper != nullptr && !mapper->is_null()) {
            revision.hasMapper = true;
            if (!isInteger(mapper) || mapper->get<std::int64_t>() < 0) {
                fail("revision mapper must be a non-negative integer");
            }
            revision.mapper = mapper->get<std::int64_t>();
        }
        if (revision.hasCapabilities) {
            checkUniqueCapabilities(
                revision.capabilities, "revision", "revision capability");
        }
        if (revision.hasResources) {
            if (revision.resources.empty()) {
                fail("revision resources must be non-empty");
            }
            checkUniqueIds(revision.resources,
                [](const ResourceSpec &value) { return value.resourceId; },
                "revision resource ids must be unique");
        }
        if (revision.hasResources && !revision.resourceOverrides.empty()) {
            fail("revision resources and resource overrides are mutually exclusive");
        }
        checkUniqueIds(revision.resourceOverrides,
            [](const ResourceOverrideSpec &value) { return value.resourceId; },
            "revision resource override ids must be unique");
        checkUniqueIds(revision.payloads,
            [](const PayloadSpec &value) { return value.payloadId; },
            "revision payload ids must be unique");

        profile.revisions.push_back(std::move(revision));
    }

    profile.gameId = requireString(member(document, "id"), "game profile id");
    profile.name = requireString(member(document, "name"), "game profile name");
    profile.platform = requireString(
        member(document, "platform"), "game profile platform");

    static_cast<void>(stableIdentifier(member(document, "id"), "game id"));
    static_cast<void>(stableIdentifier(member(document, "platform"), "platform"));
    const Json *profileVersion = member(document, "profile_version");
    if (!isInteger(profileVersion) || profileVersion->get<std::int64_t>() <= 0) {
        fail("profile version must be positive");
    }
    profile.profileVersion = profileVersion->get<std::int64_t>();
    if (profile.name.empty() || profile.revisions.empty()
        || profile.resources.empty()) {
        fail("game profile needs a name, revisions and resources");
    }
    checkUniqueCapabilities(profile.capabilities, "game profile", "capability");
    checkUniqueIds(profile.revisions,
        [](const RevisionSpec &value) { return value.revisionId; },
        "game profile revision ids must be unique");
    checkUniqueIds(profile.resources,
        [](const ResourceSpec &value) { return value.resourceId; },
        "game profile resource ids must be unique");

    for (const RevisionSpec &revision : profile.revisions) {
        std::set<std::string> payloadIds;
        for (const PayloadSpec &payload : revision.payloads) {
            payloadIds.insert(payload.payloadId);
        }
        std::set<std::string> unknown;
        for (const ResourceSpec &resource : profile.resourcesFor(revision)) {
            if (resource.hasPayload && payloadIds.count(resource.payload) == 0) {
                unknown.insert(resource.payload);
            }
        }
        if (!unknown.empty()) {
            fail("revision " + revision.revisionId
                + " has unknown resource payload '" + *unknown.begin() + "'");
        }
    }

    return profile;
}

GameProfile loadGameProfile(const std::string &path)
{
    std::ifstream stream(path, std::ios::binary);
    if (!stream) {
        fail("cannot read game profile " + path);
    }
    const std::string text(
        (std::istreambuf_iterator<char>(stream)), std::istreambuf_iterator<char>());
    return parseGameProfile(text);
}

namespace {

Json renderParameters(const std::map<std::string, Value> &values)
{
    Json object = Json::object();
    for (const auto &entry : values) {
        // Round-tripped through text so the conversion lives in exactly
        // one place; profiles are parsed once, so the cost is nothing.
        object[entry.first] = Json::parse(renderValue(entry.second));
    }
    return object;
}

bool sameResource(const ResourceSpec &left, const ResourceSpec &right)
{
    return left.resourceId == right.resourceId && left.kind == right.kind
        && left.codec == right.codec && left.capacityPolicy == right.capacityPolicy
        && left.hasPayload == right.hasPayload
        && (!left.hasPayload || left.payload == right.payload)
        && left.parameters == right.parameters;
}

Json renderResource(const ResourceSpec &resource)
{
    Json record = Json::object();
    record["id"] = resource.resourceId;
    record["kind"] = resource.kind;
    record["codec"] = resource.codec;
    record["capacity_policy"] = resource.capacityPolicy;
    record["parameters"] = renderParameters(resource.parameters);
    record["payload"] = resource.hasPayload ? Json(resource.payload) : Json(nullptr);
    return record;
}

} // namespace

std::string renderGameProfile(const GameProfile &profile)
{
    Json revisions = Json::array();
    for (const RevisionSpec &revision : profile.revisions) {
        Json record = Json::object();
        record["id"] = revision.revisionId;
        record["name"] = revision.name;
        record["size"] = revision.size;
        record["sha1"] = revision.sha1;
        record["sha256"] = revision.sha256;
        record["container"] = revision.container;
        record["mapper"] = revision.hasMapper ? Json(revision.mapper) : Json(nullptr);
        if (revision.hasCapabilities) {
            record["capabilities"] = revision.capabilities;
        } else {
            record["capabilities"] = nullptr;
        }
        if (revision.hasResources) {
            Json list = Json::array();
            for (const ResourceSpec &resource : revision.resources) {
                list.push_back(renderResource(resource));
            }
            record["resources"] = std::move(list);
        } else {
            record["resources"] = nullptr;
        }
        Json overrides = Json::array();
        for (const ResourceOverrideSpec &override : revision.resourceOverrides) {
            Json entry = Json::object();
            entry["id"] = override.resourceId;
            entry["parameters"] = renderParameters(override.parameters);
            entry["payload"] =
                override.hasPayload ? Json(override.payload) : Json(nullptr);
            overrides.push_back(std::move(entry));
        }
        record["resource_overrides"] = std::move(overrides);
        Json payloads = Json::array();
        for (const PayloadSpec &payload : revision.payloads) {
            Json entry = Json::object();
            entry["id"] = payload.payloadId;
            entry["storage"] = payload.storage;
            entry["size"] = payload.size;
            entry["sha1"] = payload.sha1;
            entry["file_offset"] =
                payload.hasFileOffset ? Json(payload.fileOffset) : Json(nullptr);
            entry["record_ids"] = payload.recordIds;
            entry["load_address"] =
                payload.hasLoadAddress ? Json(payload.loadAddress) : Json(nullptr);
            payloads.push_back(std::move(entry));
        }
        record["payloads"] = std::move(payloads);
        // What merging actually contributed, and nothing else: a revision with
        // its own list already has it above, and one with neither gets the
        // profile's list by definition. Listing only the changed entries still
        // catches a merge that touched an entry it should not have.
        if (revision.hasResources || revision.resourceOverrides.empty()) {
            record["merged_resources"] = nullptr;
        } else {
            const std::vector<ResourceSpec> merged = profile.resourcesFor(revision);
            Json changes = Json::array();
            for (std::size_t index = 0;
                index < merged.size() && index < profile.resources.size();
                ++index) {
                if (!sameResource(profile.resources[index], merged[index])) {
                    changes.push_back(renderResource(merged[index]));
                }
            }
            record["merged_resources"] = std::move(changes);
        }
        revisions.push_back(std::move(record));
    }

    Json resources = Json::array();
    for (const ResourceSpec &resource : profile.resources) {
        resources.push_back(renderResource(resource));
    }

    Json root = Json::object();
    root["id"] = profile.gameId;
    root["profile_version"] = profile.profileVersion;
    root["name"] = profile.name;
    root["platform"] = profile.platform;
    root["capabilities"] = profile.capabilities;
    root["revisions"] = std::move(revisions);
    root["resources"] = std::move(resources);
    return root.dump(2, ' ', true);
}

} // namespace retrolarium::core
