# Vendored third-party headers

Copied verbatim, never edited. Updating one means replacing the file and
recording the new version and hash here, so a diff always shows what moved.

## toml11

- File: `toml11/toml.hpp`
- Version: v4.4.0 (the `single_include` amalgamation)
- Source: https://raw.githubusercontent.com/ToruNiina/toml11/v4.4.0/single_include/toml.hpp
- SHA-256: `71a65e312d8375f4fdbca3b921c6e3d9255058ea964071dd36f674183047d260`
- Licence: MIT

Studio project files are TOML, and the core has to read them without Qt and
without Python. It is compiled into exactly one translation unit
(`src/studio_project.cpp`) because the single header is large and slow to
parse; the public core headers stay free of it.

toml++ was tried first and rejected: the cross-build image ships GCC 7.3, and
toml++ v3 needs GCC 8 or newer. Its file-reading path also calls a wide-string
`ifstream::open` that libstdc++ does not provide on MinGW.

toml11's diagnostics differ from Python's `tomllib`, so a malformed project
file produces a different message on each side. Parity covers the projection
the two loaders agree on, not the wording of syntax errors.

## nlohmann/json

- File: `nlohmann/json.hpp`
- Version: v3.11.3 (the single-header release)
- Source: https://github.com/nlohmann/json/releases/download/v3.11.3/json.hpp
- SHA-256: `9bea4c8066ef4a1c206b2be5a36302f8926f7fdc6087af5d20b417d0cf103ea6`
- Licence: MIT

Game profiles and disassembly manifests are JSON, and the core has to read them
without Qt. Its default object type is `std::map`, so `dump(2, ' ', true)`
produces the same bytes as Python's `json.dumps(value, indent=2,
sort_keys=True)`: sorted keys, two-space indent, non-ASCII escaped. That is
what lets a projection be compared to the Kit's byte for byte.

Floating-point formatting is the one place the two are not known to agree.
Neither profiles nor manifests carry floats, and the corpus does not claim
parity for them.

Each library's license sits beside it (`toml11/LICENSE`,
`nlohmann/LICENSE.MIT`, both MIT): the studio package ships them, since
the studio links the core statically.
