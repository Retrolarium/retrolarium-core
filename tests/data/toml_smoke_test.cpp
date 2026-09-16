// Proves the vendored TOML parser builds and behaves under the cross-build
// toolchain before anything depends on it.
//
// Studio project files only use a small part of TOML: tables, arrays of
// tables, strings, integers, booleans and string arrays. The cases here are
// that subset, plus the two failures the loader has to distinguish.

#include <toml.hpp>

#include <iostream>
#include <string>

namespace {

int failures = 0;

void check(bool condition, const std::string &what)
{
    if (!condition) {
        std::cerr << "FAIL: " << what << '\n';
        ++failures;
    }
}

} // namespace

int main()
{
    const std::string document = R"(schema = "retrolarium.studio.project"
schema_version = 3

[project]
id = "smb1-ju"
name = "Super Mario Bros."
platform = "nes"

[workspace]
layout = "tabbed"

[[workspace.tabs]]
id = "graphics"
kind = "nes.graphics"
capabilities = ["undo", "export"]
enabled = true

[[workspace.tabs]]
id = "levels"
kind = "smb.levels"
enabled = false
)";

    try {
        const toml::value parsed = toml::parse_str(document);
        check(parsed.at("schema").as_string() == "retrolarium.studio.project",
            "schema string round-trips");
        check(parsed.at("schema_version").as_integer() == 3, "integer round-trips");
        check(parsed.at("project").at("platform").as_string() == "nes",
            "nested table reads");

        const toml::array &tabs = parsed.at("workspace").at("tabs").as_array();
        check(tabs.size() == 2, "array of tables has two entries");
        if (tabs.size() == 2) {
            check(tabs[0].at("id").as_string() == "graphics", "first tab id reads");
            check(tabs[0].at("enabled").as_boolean(), "boolean true reads");
            check(tabs[0].at("capabilities").as_array().size() == 2,
                "string array reads");
            check(!tabs[1].at("enabled").as_boolean(), "boolean false reads");
            check(!tabs[1].contains("capabilities"), "absent key stays absent");
        }

        // Key order has to be irrelevant: the projection is built from names.
        check(parsed.contains("project") && parsed.contains("workspace"),
            "top-level tables are addressable by name");
    } catch (const std::exception &error) {
        std::cerr << "FAIL: the well-formed document did not parse: "
                  << error.what() << '\n';
        ++failures;
    }

    // A syntax error must surface as an exception rather than a silent empty
    // table, because the loader turns it into a diagnostic.
    try {
        static_cast<void>(toml::parse_str("id = \n"));
        std::cerr << "FAIL: a malformed document parsed\n";
        ++failures;
    } catch (const std::exception &) {
    }

    // A duplicate key is a parse error in TOML, not a last-one-wins merge.
    try {
        static_cast<void>(toml::parse_str("id = \"a\"\nid = \"b\"\n"));
        std::cerr << "FAIL: a duplicate key was accepted\n";
        ++failures;
    } catch (const std::exception &) {
    }

    if (failures != 0) {
        std::cerr << failures << " TOML smoke check(s) failed\n";
        return 1;
    }
    std::cout << "TOML smoke: vendored toml11 v" << TOML11_VERSION_MAJOR << '.'
              << TOML11_VERSION_MINOR << '.' << TOML11_VERSION_PATCH
              << " behaves\n";
    return 0;
}
