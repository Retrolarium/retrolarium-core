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
