#include <retrolarium/core/studio_project.hpp>

// The vendored TOML parser is heavy to compile, so it is included here and
// nowhere else. See third_party/README.md.
#include <toml.hpp>

// GCC 7, which the cross-build image ships, only has the filesystem TS. It is
// missing weakly_canonical and lexically_relative, so both are open-coded
// below rather than switched on per toolchain.
#if defined(__has_include) && __has_include(<filesystem>)
#    include <filesystem>
namespace stdfs = std::filesystem;
#else
#    include <experimental/filesystem>
namespace stdfs = std::experimental::filesystem;
#endif

#include <algorithm>
#include <cctype>
#include <functional>
#include <set>
#include <sstream>

namespace retrolarium::core {
namespace {

namespace fs = stdfs;

constexpr const char *kSchema = "retrolarium.project";
constexpr int kSchemaVersion = 1;
constexpr const char *kInspectionSchema = "retrolarium.project-inspection";
constexpr const char *kProjectSuffix = ".rlj";

[[noreturn]] void fail(const std::string &context, const std::string &message)
{
    throw StudioProjectError(context + ": " + message);
}

const std::set<std::string> kSourceModes {"binary-profile", "source-project"};
const std::set<std::string> kLayouts {"auto", "single-row", "two-row"};
const std::set<std::string> kGroups {"content", "assets", "tools"};
const std::set<std::string> kPlatforms {"nes", "snes", "megadrive"};

const std::set<std::string> kEditorKinds {
    "animation.mapping", "audio.sequencer", "audio.synthesis", "castle.rooms",
    "code.analysis", "graphics.tile-set", "level.procedural", "level.tile-grid",
    "metatile.composer", "palette.set", "screen.tilemap", "text.fixed",
    "world.routing",
};

const std::set<std::string> kCodecs {
    "castle.object-stream@1", "castle.prefix-rooms@1", "fds.synthesis.v1",
    "fds.music.v1", "nes.chr-2bpp.v1", "nes.fixed-text-fields.v1",
    "nes.metatile-2x2.v1", "nes.nametable.v1", "nes.palette-table.v1",
    "nes.ppu-palette-packets.v1", "nes.ppu-screen-packets.v1",
    "pacman.maze-rle.v1", "pacman.maze-rle@1", "pacman.actor-mapping.v1",
    "pacman.palette-table.v1", "pacman.screen-collection.v1",
    "pacman.sound-streams.v1", "pacman.sound@1",
    "retrolarium.megadrive.disassembly@1", "retrolarium.nes.disassembly@1",
    "retrolarium.snes.disassembly@1", "smb.apu@1", "smb.apu-envelope.v1",
    "smb.apu-music.v1", "smb.area@1", "smb.world.v1", "smb.levels.v1",
    "smb.player-frames.v1",
};

const std::set<std::string> kCapabilities {
    "changed-markers", "build", "compose", "edit", "eyedropper", "midi-import",
    "navigate", "paint", "piano-roll", "pixel-paint", "playtest", "preview",
    "restore", "run", "semantic-overlays", "undo", "wav-preview",
};

const std::set<std::string> kOperations {
    "project.build", "project.launch", "project.validate", "project.verify",
};

bool isBlank(const std::string &value)
{
    return std::all_of(value.begin(), value.end(), [](char character) {
        return std::isspace(static_cast<unsigned char>(character)) != 0;
    });
}

// Mirrors _IDENTIFIER: ^[a-z][a-z0-9_.-]*$
bool isIdentifier(const std::string &value)
{
    if (value.empty() || value.front() < 'a' || value.front() > 'z') return false;
    return std::all_of(value.begin() + 1, value.end(), [](char character) {
        return (character >= 'a' && character <= 'z')
            || (character >= '0' && character <= '9')
            || character == '_' || character == '.' || character == '-';
    });
}

bool isSha256(const std::string &value)
{
    if (value.size() != 64) return false;
    return std::all_of(value.begin(), value.end(), [](char character) {
        return (character >= '0' && character <= '9')
            || (character >= 'a' && character <= 'f');
    });
}

// toml11 tables are unordered, so every place that reports a field name walks
// a sorted copy instead. That is what makes the reported field the same one
// the Kit reports.
std::set<std::string> sortedKeys(const toml::value &table)
{
    std::set<std::string> keys;
    for (const auto &entry : table.as_table()) {
        keys.insert(entry.first);
    }
    return keys;
}

const toml::value *member(const toml::value &table, const std::string &name)
{
    const auto &entries = table.as_table();
    const auto found = entries.find(name);
    return found == entries.end() ? nullptr : &found->second;
}

const toml::value &requireTable(
    const toml::value &parent, const std::string &name, const std::string &context)
{
    const toml::value *node = member(parent, name);
    if (node == nullptr || !node->is_table()) {
        fail(context, "must be a table");
    }
    return *node;
}

void checkKeys(const toml::value &table, const std::string &context,
    const std::set<std::string> &allowed, const std::set<std::string> &required)
{
    for (const std::string &key : sortedKeys(table)) {
        if (allowed.count(key) == 0) {
            fail(context, "unknown field '" + key + "'");
        }
    }
    const std::set<std::string> present = sortedKeys(table);
    for (const std::string &key : required) {
        if (present.count(key) == 0) {
            fail(context, "missing field '" + key + "'");
        }
    }
}

std::string requireString(const toml::value *node, const std::string &context)
{
    if (node == nullptr || !node->is_string()) {
        fail(context, "must be a non-empty string");
    }
    const std::string value = node->as_string();
    if (value.empty() || isBlank(value)) {
        fail(context, "must be a non-empty string");
    }
    return value;
}

std::string requireIdentifier(const toml::value *node, const std::string &context)
{
    const std::string value = requireString(node, context);
    if (!isIdentifier(value)) {
        fail(context, "must match [a-z][a-z0-9_.-]*");
    }
    return value;
}

std::string requireChoice(const toml::value *node, const std::string &context,
    const std::set<std::string> &choices)
{
    const std::string value = requireString(node, context);
    if (choices.count(value) == 0) {
        fail(context, "unsupported value '" + value + "'");
    }
    return value;
}

std::vector<std::string> requireStringList(
    const toml::value *node, const std::string &context)
{
    if (node == nullptr) return {};
    if (!node->is_array()) {
        fail(context, "must be an array");
    }
    const toml::array &array = node->as_array();
    std::vector<std::string> result;
    for (std::size_t index = 0; index < array.size(); ++index) {
        result.push_back(requireString(
            &array[index], context + "[" + std::to_string(index) + "]"));
    }
    const std::set<std::string> unique(result.begin(), result.end());
    if (unique.size() != result.size()) {
        fail(context, "must not contain duplicates");
    }
    return result;
}

std::vector<std::string> splitPosix(const std::string &value)
{
    std::vector<std::string> parts;
    std::istringstream stream(value);
    std::string part;
    while (std::getline(stream, part, '/')) {
        parts.push_back(part);
    }
    return parts;
}

fs::path absolutePath(const fs::path &value)
{
    if (value.is_absolute()) return value;
    std::error_code error;
    const fs::path here = fs::current_path(error);
    return error ? value : here / value;
}

// The filesystem TS has no lexically_normal, and the project contract forbids
// ".." in stored paths anyway, so this only has to collapse what the caller's
// own working directory contributes.
fs::path lexicalNormal(const fs::path &value)
{
    fs::path result = value.root_path();
    std::vector<fs::path> parts;
    for (const fs::path &part : value.relative_path()) {
        if (part == ".") continue;
        if (part == ".." && !parts.empty() && parts.back() != "..") {
            parts.pop_back();
            continue;
        }
        parts.push_back(part);
    }
    for (const fs::path &part : parts) {
        result /= part;
    }
    return result;
}

bool isInside(const fs::path &root, const fs::path &candidate)
{
    auto rootPart = root.begin();
    auto candidatePart = candidate.begin();
    for (; rootPart != root.end(); ++rootPart, ++candidatePart) {
        if (candidatePart == candidate.end() || *candidatePart != *rootPart) {
            return false;
        }
    }
    return candidatePart != candidate.end();
}

// Mirrors _project_path: the stored form stays relative and portable, while
// the resolved form has to land inside the project directory.
std::pair<std::string, fs::path> projectPath(
    const fs::path &root, const toml::value *node, const std::string &context)
{
    const std::string source = requireString(node, context);
    if (source.find('\\') != std::string::npos) {
        fail(context, "must use portable forward slashes");
    }
    if (source.front() == '/') {
        fail(context, "absolute paths are forbidden");
    }
    // A Windows drive letter is absolute too, even without a leading slash.
    if (source.size() >= 2 && source[1] == ':') {
        fail(context, "absolute paths are forbidden");
    }
    const std::vector<std::string> parts = splitPosix(source);
    if (parts.empty()) {
        fail(context, "must be a normalized relative path without '..'");
    }
    for (const std::string &part : parts) {
        if (part.empty() || part == "." || part == "..") {
            fail(context, "must be a normalized relative path without '..'");
        }
    }

    fs::path resolved = root;
    for (const std::string &part : parts) {
        resolved /= part;
    }
    std::error_code error;
    const fs::path canonical = fs::canonical(resolved, error);
    if (error) {
        fail(context, "file does not exist: " + source);
    }
    if (!isInside(root, canonical)) {
        fail(context, "path escapes the project directory");
    }
    if (!fs::is_regular_file(canonical, error) || error) {
        fail(context, "file does not exist: " + source);
    }
    return {source, canonical};
}

// --- the fixed projection, rendered the way `rltool studio inspect` prints it

struct JsonNode {
    enum class Kind { Null, Bool, Int, String, Array, Object } kind = Kind::Null;
    bool boolean = false;
    long long integer = 0;
    std::string text;
    std::vector<JsonNode> items;
    // std::map keeps the keys sorted, which is what sort_keys=True produces.
    std::map<std::string, JsonNode> members;

    static JsonNode string(std::string value)
    {
        JsonNode node;
        node.kind = Kind::String;
        node.text = std::move(value);
        return node;
    }
    static JsonNode number(long long value)
    {
        JsonNode node;
        node.kind = Kind::Int;
        node.integer = value;
        return node;
    }
    static JsonNode flag(bool value)
    {
        JsonNode node;
        node.kind = Kind::Bool;
        node.boolean = value;
        return node;
    }
    static JsonNode null() { return JsonNode(); }
    static JsonNode array(std::vector<JsonNode> value)
    {
        JsonNode node;
        node.kind = Kind::Array;
        node.items = std::move(value);
        return node;
    }
    static JsonNode object(std::map<std::string, JsonNode> value)
    {
        JsonNode node;
        node.kind = Kind::Object;
        node.members = std::move(value);
        return node;
    }
};

JsonNode stringArray(const std::vector<std::string> &values)
{
    std::vector<JsonNode> items;
    items.reserve(values.size());
    for (const std::string &value : values) {
        items.push_back(JsonNode::string(value));
    }
    return JsonNode::array(std::move(items));
}

void appendEscaped(std::string &out, const std::string &value)
{
    const auto appendUnicode = [&out](unsigned int code) {
        static constexpr char kDigits[] = "0123456789abcdef";
        out += "\\u";
        out += kDigits[(code >> 12) & 0xF];
        out += kDigits[(code >> 8) & 0xF];
        out += kDigits[(code >> 4) & 0xF];
        out += kDigits[code & 0xF];
    };

    out += '"';
    for (std::size_t index = 0; index < value.size();) {
        const unsigned char byte = static_cast<unsigned char>(value[index]);
        if (byte == '"') { out += "\\\""; ++index; continue; }
        if (byte == '\\') { out += "\\\\"; ++index; continue; }
        if (byte == '\n') { out += "\\n"; ++index; continue; }
        if (byte == '\r') { out += "\\r"; ++index; continue; }
        if (byte == '\t') { out += "\\t"; ++index; continue; }
        if (byte == '\b') { out += "\\b"; ++index; continue; }
        if (byte == '\f') { out += "\\f"; ++index; continue; }
        if (byte < 0x20) { appendUnicode(byte); ++index; continue; }
        if (byte < 0x80) { out += static_cast<char>(byte); ++index; continue; }

        // json.dumps defaults to ensure_ascii, so anything above ASCII leaves
        // as one or two \u escapes.
        unsigned int code = 0;
        std::size_t length = 0;
        if ((byte & 0xE0) == 0xC0) { code = byte & 0x1Fu; length = 2; }
        else if ((byte & 0xF0) == 0xE0) { code = byte & 0x0Fu; length = 3; }
        else if ((byte & 0xF8) == 0xF0) { code = byte & 0x07u; length = 4; }
        else {
            throw StudioProjectError("project text is not valid UTF-8");
        }
        if (index + length > value.size()) {
            throw StudioProjectError("project text is not valid UTF-8");
        }
        for (std::size_t offset = 1; offset < length; ++offset) {
            const unsigned char continuation =
                static_cast<unsigned char>(value[index + offset]);
            if ((continuation & 0xC0) != 0x80) {
                throw StudioProjectError("project text is not valid UTF-8");
            }
            code = (code << 6) | (continuation & 0x3Fu);
        }
        index += length;
        if (code > 0xFFFF) {
            const unsigned int adjusted = code - 0x10000u;
            appendUnicode(0xD800u + (adjusted >> 10));
            appendUnicode(0xDC00u + (adjusted & 0x3FFu));
        } else {
            appendUnicode(code);
        }
    }
    out += '"';
}

void render(const JsonNode &node, std::string &out, int depth)
{
    const std::string indent(static_cast<std::size_t>(depth + 1) * 2, ' ');
    const std::string closing(static_cast<std::size_t>(depth) * 2, ' ');
    switch (node.kind) {
    case JsonNode::Kind::Null:
        out += "null";
        return;
    case JsonNode::Kind::Bool:
        out += node.boolean ? "true" : "false";
        return;
    case JsonNode::Kind::Int:
        out += std::to_string(node.integer);
        return;
    case JsonNode::Kind::String:
        appendEscaped(out, node.text);
        return;
    case JsonNode::Kind::Array: {
        if (node.items.empty()) {
            out += "[]";
            return;
        }
        out += "[\n";
        for (std::size_t index = 0; index < node.items.size(); ++index) {
            out += indent;
            render(node.items[index], out, depth + 1);
            if (index + 1 < node.items.size()) out += ',';
            out += '\n';
        }
        out += closing;
        out += ']';
        return;
    }
    case JsonNode::Kind::Object: {
        if (node.members.empty()) {
            out += "{}";
            return;
        }
        out += "{\n";
        std::size_t index = 0;
        for (const auto &entry : node.members) {
            out += indent;
            appendEscaped(out, entry.first);
            out += ": ";
            render(entry.second, out, depth + 1);
            if (++index < node.members.size()) out += ',';
            out += '\n';
        }
        out += closing;
        out += '}';
        return;
    }
    }
}

void validateDependencyGraph(const std::vector<StudioTab> &tabs)
{
    std::map<std::string, const StudioTab *> byId;
    for (const StudioTab &tab : tabs) {
        byId[tab.id] = &tab;
    }
    for (const StudioTab &tab : tabs) {
        for (const std::string &dependency : tab.dependsOn) {
            const auto found = byId.find(dependency);
            if (found == byId.end()) {
                fail("workspace.tabs." + tab.id + ".depends_on",
                    "unknown tab '" + dependency + "'");
            }
            if (tab.enabled && !found->second->enabled) {
                fail("workspace.tabs." + tab.id + ".depends_on",
                    "enabled tab depends on disabled tab '" + dependency + "'");
            }
        }
    }

    std::set<std::string> visiting;
    std::set<std::string> visited;
    std::function<void(const std::string &)> visit =
        [&](const std::string &tabId) {
            if (visiting.count(tabId) != 0) {
                fail("workspace.tabs", "dependency cycle contains '" + tabId + "'");
            }
            if (visited.count(tabId) != 0) return;
            visiting.insert(tabId);
            for (const std::string &dependency : byId[tabId]->dependsOn) {
                visit(dependency);
            }
            visiting.erase(tabId);
            visited.insert(tabId);
        };
    // Document order, not sorted order: when several tabs sit on a cycle the
    // Kit names the first one it reaches, and that is the order it walks.
    for (const StudioTab &tab : tabs) {
        visit(tab.id);
    }
}

} // namespace

StudioInspection loadStudioProject(const std::string &path)
{
    fs::path projectFile = lexicalNormal(absolutePath(fs::path(path)));
    if (projectFile.extension().string() != kProjectSuffix) {
        throw StudioProjectError(
            path + ": project file must use the " + kProjectSuffix + " extension");
    }
    std::error_code error;
    projectFile = fs::canonical(projectFile, error);
    if (error || !fs::is_regular_file(projectFile, error)) {
        throw StudioProjectError("cannot read Studio project " + path);
    }
    const fs::path root = projectFile.parent_path();

    toml::value source;
    try {
        source = toml::parse(projectFile.string());
    } catch (const std::exception &parseError) {
        // toml11 and Python's tomllib word syntax errors differently; only the
        // fact of the failure is contractual.
        throw StudioProjectError(
            projectFile.string() + ": " + parseError.what());
    }
    if (!source.is_table()) {
        fail(projectFile.string(), "must be a table");
    }

    checkKeys(source, "project",
        {"schema", "schema_version", "project", "source", "workspace", "operations"},
        {"schema", "schema_version", "project", "source", "workspace"});
    const toml::value *schema = member(source, "schema");
    const toml::value *schemaVersion = member(source, "schema_version");
    if (schema == nullptr || !schema->is_string()
        || schema->as_string() != kSchema
        || schemaVersion == nullptr || !schemaVersion->is_integer()
        || schemaVersion->as_integer() != kSchemaVersion) {
        fail("project", std::string("expected '") + kSchema + "' version "
            + std::to_string(kSchemaVersion));
    }

    const toml::value &metadata = requireTable(source, "project", "project");
    checkKeys(metadata, "project",
        {"id", "name", "platform", "profile", "source_mode"},
        {"id", "name", "platform", "profile", "source_mode"});

    StudioInspection result;
    result.projectFile = projectFile.string();
    result.projectRoot = root.string();
    result.id = requireIdentifier(member(metadata, "id"), "project.id");
    result.name = requireString(member(metadata, "name"), "project.name");
    result.platform = requireChoice(
        member(metadata, "platform"), "project.platform", kPlatforms);
    result.profile = requireIdentifier(
        member(metadata, "profile"), "project.profile");
    result.sourceMode = requireChoice(
        member(metadata, "source_mode"), "project.source_mode", kSourceModes);

    const toml::value &sourceTable = requireTable(source, "source", "source");
    checkKeys(sourceTable, "source", {"disassembly", "sha256"},
        {"disassembly", "sha256"});
    const auto disassembly = projectPath(
        root, member(sourceTable, "disassembly"), "source.disassembly");
    result.disassembly = disassembly.first;
    result.disassemblyPath = disassembly.second.string();
    result.sourceSha256 = requireString(
        member(sourceTable, "sha256"), "source.sha256");
    if (!isSha256(result.sourceSha256)) {
        fail("source.sha256", "must be 64 lowercase hexadecimal characters");
    }

    const toml::value &workspace = requireTable(source, "workspace", "workspace");
    checkKeys(workspace, "workspace", {"layout", "startup_tab", "tabs"},
        {"layout", "tabs"});
    result.layout = requireChoice(
        member(workspace, "layout"), "workspace.layout", kLayouts);

    const toml::value *rawTabs = member(workspace, "tabs");
    if (rawTabs == nullptr || !rawTabs->is_array() || rawTabs->as_array().empty()) {
        fail("workspace.tabs", "must contain at least one tab");
    }
    const toml::array &tabArray = rawTabs->as_array();
    std::set<std::string> tabIds;
    for (std::size_t index = 0; index < tabArray.size(); ++index) {
        const std::string context = "workspace.tabs[" + std::to_string(index) + "]";
        const toml::value &raw = tabArray[index];
        if (!raw.is_table()) fail(context, "must be a table");
        checkKeys(raw, context,
            {"id", "title", "kind", "group", "document", "codec", "capabilities",
                "depends_on", "enabled"},
            {"id", "title", "kind", "group", "codec"});

        StudioTab tab;
        tab.id = requireIdentifier(member(raw, "id"), context + ".id");
        if (!tabIds.insert(tab.id).second) {
            fail(context + ".id", "duplicate tab id '" + tab.id + "'");
        }
        tab.title = requireString(member(raw, "title"), context + ".title");
        tab.kind = requireChoice(member(raw, "kind"), context + ".kind", kEditorKinds);
        tab.group = requireChoice(member(raw, "group"), context + ".group", kGroups);
        tab.codec = requireChoice(member(raw, "codec"), context + ".codec", kCodecs);

        const toml::value *enabled = member(raw, "enabled");
        if (enabled != nullptr) {
            if (!enabled->is_boolean()) {
                fail(context + ".enabled", "must be a boolean");
            }
            tab.enabled = enabled->as_boolean();
        }

        tab.capabilities = requireStringList(
            member(raw, "capabilities"), context + ".capabilities");
        std::set<std::string> unknownCapabilities;
        for (const std::string &capability : tab.capabilities) {
            if (kCapabilities.count(capability) == 0) {
                unknownCapabilities.insert(capability);
            }
        }
        if (!unknownCapabilities.empty()) {
            fail(context + ".capabilities",
                "unsupported value '" + *unknownCapabilities.begin() + "'");
        }
        tab.dependsOn = requireStringList(
            member(raw, "depends_on"), context + ".depends_on");

        if (member(raw, "document") != nullptr) {
            const auto document = projectPath(
                root, member(raw, "document"), context + ".document");
            tab.document = document.first;
            tab.documentPath = document.second.string();
        } else if (tab.kind != "code.analysis") {
            fail(context + ".document", "is required for this editor kind");
        }
        result.tabs.push_back(std::move(tab));
    }

    validateDependencyGraph(result.tabs);

    std::vector<std::string> enabledIds;
    for (const StudioTab &tab : result.tabs) {
        if (tab.enabled) enabledIds.push_back(tab.id);
    }
    if (enabledIds.empty()) {
        fail("workspace.tabs", "must contain at least one enabled tab");
    }
    const toml::value *startup = member(workspace, "startup_tab");
    result.startupTab = startup == nullptr
        ? enabledIds.front()
        : requireIdentifier(startup, "workspace.startup_tab");
    if (std::find(enabledIds.begin(), enabledIds.end(), result.startupTab)
        == enabledIds.end()) {
        fail("workspace.startup_tab", "must name an enabled tab");
    }

    const toml::value *operations = member(source, "operations");
    if (operations != nullptr) {
        if (!operations->is_table()) fail("operations", "must be a table");
        checkKeys(*operations, "operations",
            {"validate", "build", "verify", "launch"}, {});
        for (const std::string &name : sortedKeys(*operations)) {
            const std::string context = "operations." + name;
            const std::string operation = requireChoice(
                member(*operations, name), context, kOperations);
            const std::string expected = "project." + name;
            if (operation != expected) {
                fail(context, "must use registered operation '" + expected + "'");
            }
            result.operations[name] = operation;
        }
    }

    return result;
}

std::string renderStudioInspection(const StudioInspection &value)
{
    std::vector<JsonNode> tabs;
    tabs.reserve(value.tabs.size());
    for (const StudioTab &tab : value.tabs) {
        tabs.push_back(JsonNode::object({
            {"id", JsonNode::string(tab.id)},
            {"title", JsonNode::string(tab.title)},
            {"kind", JsonNode::string(tab.kind)},
            {"group", JsonNode::string(tab.group)},
            {"codec", JsonNode::string(tab.codec)},
            {"capabilities", stringArray(tab.capabilities)},
            {"depends_on", stringArray(tab.dependsOn)},
            {"enabled", JsonNode::flag(tab.enabled)},
            {"document", tab.document.empty()
                    ? JsonNode::null() : JsonNode::string(tab.document)},
            {"document_path", tab.documentPath.empty()
                    ? JsonNode::null() : JsonNode::string(tab.documentPath)},
        }));
    }

    std::map<std::string, JsonNode> operations;
    for (const auto &entry : value.operations) {
        operations[entry.first] = JsonNode::string(entry.second);
    }

    const JsonNode root = JsonNode::object({
        {"schema", JsonNode::string(kInspectionSchema)},
        {"schema_version", JsonNode::number(1)},
        {"project_file", JsonNode::string(value.projectFile)},
        {"project_root", JsonNode::string(value.projectRoot)},
        {"project", JsonNode::object({
            {"id", JsonNode::string(value.id)},
            {"name", JsonNode::string(value.name)},
            {"platform", JsonNode::string(value.platform)},
            {"profile", JsonNode::string(value.profile)},
            {"source_mode", JsonNode::string(value.sourceMode)},
        })},
        {"source", JsonNode::object({
            {"disassembly", JsonNode::string(value.disassembly)},
            {"disassembly_path", JsonNode::string(value.disassemblyPath)},
            {"sha256", JsonNode::string(value.sourceSha256)},
            {"schema", JsonNode::string(value.sourceSchema)},
        })},
        {"workspace", JsonNode::object({
            {"layout", JsonNode::string(value.layout)},
            {"startup_tab", JsonNode::string(value.startupTab)},
            {"tabs", JsonNode::array(std::move(tabs))},
        })},
        {"operations", JsonNode::object(std::move(operations))},
    });

    std::string out;
    render(root, out, 0);
    return out;
}

} // namespace retrolarium::core
