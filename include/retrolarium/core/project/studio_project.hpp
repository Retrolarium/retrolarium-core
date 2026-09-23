#pragma once

#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace retrolarium::core {

// Raised when a .rlj project violates the public contract. The message carries
// the offending field, matching the Kit's "context: reason" shape so the two
// loaders can be compared on more than exit status.
class StudioProjectError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

struct StudioTab final {
    std::string id;
    std::string title;
    std::string kind;
    std::string group;
    // Empty only for code.analysis tabs, which are the one kind allowed to
    // exist without a document.
    std::string document;
    std::string documentPath;
    std::string codec;
    std::vector<std::string> capabilities;
    std::vector<std::string> dependsOn;
    bool enabled = true;
};

struct StudioInspection final {
    std::string projectFile;
    std::string projectRoot;

    std::string id;
    std::string name;
    std::string platform;
    std::string profile;
    std::string sourceMode;

    // In flicky-content mode these carry source.manifest / manifest_path;
    // other source modes carry source.disassembly / disassembly_path.
    std::string disassembly;
    std::string disassemblyPath;
    std::string sourceSha256;
    // Read from the selected manifest (synthetic for Flicky's content format).
    std::string sourceSchema;

    std::string layout;
    std::string startupTab;
    std::vector<StudioTab> tabs;

    // Declared operations, keyed by the short name the project uses
    // ("build" -> "project.build").
    std::map<std::string, std::string> operations;
};

// Reads and validates a .rlj file and its selected source manifest.
[[nodiscard]] StudioInspection loadStudioProject(const std::string &path);

// The projection the GUI consumes, rendered exactly as
// `rltool studio inspect` prints it: sorted keys, two-space indent, non-ASCII
// escaped.
[[nodiscard]] std::string renderStudioInspection(const StudioInspection &value);

} // namespace retrolarium::core
