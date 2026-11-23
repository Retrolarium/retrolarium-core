# Retrolarium Core

The part of Retrolarium that Studio, Kit and Disassembler share. The core has
two halves: a C++ library with the `rlcore` tool, which holds the Mega Drive
compressions (Nemesis, Enigma), and the Python layer `python/retrolarium_core`,
which holds the containers, the manifest contracts and the repository guards. A
format is implemented once: in C++ where the Studio needs it too, otherwise in
Python.

```text
                 ┌── static linking ────────────> retrolarium-studio (Qt)
retrolarium-core ├── rlcore ─────────────────────> retrolarium-kit
                 └── python/retrolarium_core ────> retrolarium-kit,
                                                   retrolarium-disassembler
```

## Why it stands apart

Both sides need compression at the same time. The kit cannot cut a ROM apart
without unpacking it: a compressed block's bounds are known only after it is
unpacked. The editor cannot show graphics without unpacking them, nor save them
without packing them again.

Flicky's source reconstruction supplies the resource layout and the user's ROM.
The kit's `games/flicky/content.py` imports that source snapshot, and
`games/flicky/workspace/graphics.py` reads and stages its graphics documents
through `retrolarium_core.tool` and the core's `rlcore` codecs. Studio's
`plugins/games/flicky` supplies the editor and renderer.

These callers share the same preservation rule. When the decoded content did not
change, a round trip retains the original compressed bytes. The codec's
reference stream lets edits reuse its original code table. Keeping this logic in
one implementation makes source builds and editor saves agree.

## Boundary rules

1. **No Qt.** The core builds and is tested without Qt and without a display.
   That is what lets the kit ship `rlcore` as an ordinary pinned binary.
2. **No game semantics.** Containers, compression and tile formats live here.
   The resource codecs of particular games live in the kit
   (`retrolarium_kit/games/<game>/`).
3. **One-way dependency.** The core knows nothing of the studio, the kit or the
   disassembler: the C++ includes none of their headers and the Python layer
   imports none of them (`tests/python/test_layers.py` checks it).
4. **Logic in the library, not the CLI.** `cli/main.cpp` only parses arguments;
   everything with behaviour lives in `src/` and is covered by tests.

## Building

Building the native library needs CMake 3.21+ and a C++17 compiler (MSVC 2019+,
GCC or Clang). The Python layer and test runner need Python 3.11+ and Git.
Windows end users get `rlcore.exe` with Studio; developers find it in
`build/Release/rlcore.exe` with Visual Studio, or `build/rlcore.exe` with a
single-configuration generator.

From the root of this repository:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
ctest --test-dir build -C Release --output-on-failure
python tools/test.py --suite python
```

Native cases are registered once for CTest and `tools/test.py`; both use the
same arguments and expected exit codes. `make` selects `python` on Windows and
`python3` elsewhere; `make PYTHON=...` overrides that choice.

Retrolarium Studio adds the core with `add_subdirectory` from a
`retrolarium-core` checkout beside it, without the core's tests: run them here.

`-DRETROLARIUM_SANITIZE=ON` builds the library, `rlcore` and the tests with
AddressSanitizer and UndefinedBehaviorSanitizer (GCC or Clang).
`-DRETROLARIUM_FUZZ=ON` (Clang) adds libFuzzer targets for the Nemesis and
Enigma decoders; `fuzz/seed_corpus.py` writes the golden streams as seeds:

```sh
cmake -S . -B build-fuzz -DCMAKE_CXX_COMPILER=clang++ -DRETROLARIUM_FUZZ=ON
cmake --build build-fuzz --target retrolarium-core-fuzz-nemesis
python fuzz/seed_corpus.py tests/fixtures/megadrive/nemesis_golden.txt build-fuzz/seeds/nemesis
build-fuzz/retrolarium-core-fuzz-nemesis -max_total_time=60 build-fuzz/seeds/nemesis
```

## Contents

| Module    | Purpose                                         |
| --------- | ----------------------------------------------- |
| `nemesis` | unpacking and repacking Mega Drive tile streams |
| `enigma`  | unpacking and packing Flicky's Enigma tile maps |

Repacking Nemesis needs a reference stream: the code table sits inside the
stream itself, so the encoder reuses the original's header and table instead of
inventing its own. That removes the one truly lossy decision in the format.
Unchanged content stays byte-identical through the pair: the caller compares the
unpacked content and returns the original bytes when it did not change.

Nemesis and Enigma exist only in C++, which the kit runs as `rlcore`. Their
corpora (`tests/fixtures/megadrive/*_golden.txt`) were written by Python
implementations ported independently from the Flicky disassembly, removed once
the C++ became the only one; they stay the frozen reference the C++ must match.

The Enigma codec is the variant Flicky's 68000 decoder reads, not the standard
EniDec of the Sonic games. The header, the commands and the bit packing are the
same; the flag mask differs. In Flicky's variant mask bit 0 enables the V-flip
bit of each inline tile and mask bit 1 the H-flip bit (the standard EniDec has
them the other way round), and mask bits 2 to 4, priority and palette in the
standard EniDec, are ignored. A stream with a zero flag mask, which is what the
encoder writes, decodes the same under both. A standard EniDec for other games
is not implemented yet.

The Enigma encoder optimises: it searches for the cheapest sequence of commands.
It matches the corpus because the order in which candidates are tried and the
rule "on a tie the first wins" are fixed. They must not change: the stream would
stay valid but would no longer match.

There are no game codecs here, and there will be none: `smb.*`, `pacman.*` and
`castle-excellent.*` live in the kit. Kosinski and Saxman wait for real Sonic
data or an independent implementation: without an independent check a codec
would only be tested against itself.

## Python layer

`python/retrolarium_core` holds what both the kit and the disassembler need,
without any game semantics:

| Module      | Purpose                                                        |
| ----------- | -------------------------------------------------------------- |
| `ines`      | the iNES 1.0 container and mapper profiles (`profiles/`)       |
| `fds`       | a Famicom Disk System side: blocks, files, payload ranges      |
| `megadrive` | a Mega Drive cartridge: header, checksum, vectors              |
| `snes`      | a LoROM/HiROM cartridge: header, copier prefix, bus windows    |
| `contracts` | the contract of a disassembled project's manifest (`schemas/`) |
| `tool`      | finding and running `rlcore`                                   |
| `host`      | stable names for the host platform (`windows-x86_64`)          |

The package installs as `retrolarium-core` (`pyproject.toml` at the root). The
kit and the disassembler find it on their own when run from source: in a
`retrolarium-core` checkout beside them.

## How the kit uses it

The kit imports the Python layer directly. It does not link the C++ core; it
runs `rlcore` as a program (as it runs `ca65`) through `retrolarium_core.tool`,
which looks for the binary in this order: `RETROLARIUM_CORE` (the Studio names
the `rlcore` it ships there), a payload inside the wheel
(`retrolarium_core/_core`), then `PATH`. The build tree of a checkout
(`build/rlcore`) is used only with `RETROLARIUM_CORE_DEV=1`. Before its first
command the bridge checks that `rlcore version` reports the package's own
version, and refuses another: `pyproject.toml`, `retrolarium_core.__version__`
and `project(VERSION)` in `CMakeLists.txt`, from which CMake generates the
version `rlcore` prints, carry one number (`tests/python/test_version.py`).

```sh
rlcore nemesis decompress art.nem art.bin
rlcore nemesis compress art.bin art.nem repacked.nem
rlcore enigma decompress map.eni map.bin
rlcore enigma compress map.bin map.eni
```

`rlcore` prints one JSON line for successful codec commands; `rlcore version`
prints the plain version string. It exits with 1 when a codec refuses the data,
2 on a usage error (an unknown command, a base tile that is not a whole number
from 0 to 0xFFFF) and 3 when a file cannot be read or written; the message names
the file. Output is written to a uniquely named file beside the target and moved
over it, after an `fsync` on POSIX.

## Name guard

Retrolarium carries nothing taken from a game: no names of its characters,
enemies, items or places, and no tables copied from it. The game repositories
keep those (`config/names.json` and the game's profile,
`config/game_profile.json`, read when a project opens). The name guard checks a
repository against the names they mark as distinctive, stored only as SHA-256
digests (`retrolarium_core/name_guard.sha256`), and against literal runs of 24
numbers or more outside `third_party` trees and the files its
`name_guard_tables.txt` explains. Game titles stay. Core, kit, studio and
disassembler run it in their tests.

```powershell
python -m retrolarium_core.name_guard check path\to\repository
python -m retrolarium_core.name_guard tables path\to\repository
python -m retrolarium_core.name_guard update path\to\game-repositories
```

## Stop words and Git hooks

Private words (the owner's folders, employers, identities and internal project
names) must never reach a public repository. They are listed outside every
repository, in a `.stopwords` file that Git ignores: the first one found in the
repository's folder or a folder above it, or the file `RETROLARIUM_STOPWORDS`
names. The list has `[en]` and `[ru]` sections of words and an `[allow]` section
of longer texts in which a word is fine. Matching ignores case; inside a word,
`_`, `-` and a space match any one of them or nothing; a stem finds its
inflected forms. Without a list every check says in capitals that the stop words
were not checked: locally that is a warning, but when `CI` is set and for the
pre-push check it is a failure.

```powershell
python -m retrolarium_core.stop_words check path\to\repository
python -m retrolarium_core.stop_words history path\to\repository
python -m retrolarium_core.stop_words where
```

`check` reads a working tree (contents and paths); `history` reads everything
reachable from the branches and tags: commit and tag messages, author, committer
and tagger identities, every path and the contents of every blob. The tests of
core, kit, studio and disassembler check the tree, and the history when they run
in a clone of their own repository.

`retrolarium_core.hooks` makes Git run the checks. Each repository,
Retrolarium's and the games', installs it once per clone, here with
`make hooks`:

- **pre-commit** checks the staged changes, then runs `make lint` and
  `make format-check` when the Makefile has them;
- **commit-msg** checks the message and the author and committer identities;
- **pre-push** checks everything the push sends.

`install --env NAME=VALUE` sets a variable for the hooks and the make targets
they run; the kit's `rltool hooks install` sets `RLTOOL` that way for the game
repositories.

`make lint` checks the tree for stop words; `make format` runs the available
formatters for tracked Markdown, Python, C/C++, Lua, PowerShell, JSON, TOML,
Java and shell files. `make format-check` only reports. Missing formatters are
named in the output; see `retrolarium_core.formatting` for their commands.

## Trademarks

The games are named only to say which ones Retrolarium works with. Their titles
and characters are trademarks of their owners, who have not made or endorsed
Retrolarium. Retrolarium does not include the games: you need your own copy of
each.

## License

Retrolarium Core is free software: you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your option) any
later version (`GPL-3.0-or-later`, text in `LICENSE`). It comes without any
warranty.

## Portable test runner

The same entrypoint runs on Windows, Linux and macOS with Python 3.11 or later.
Clone the current `retrolarium-core` beside the other products (or install a
Core that includes `retrolarium_core.testing`). The runner selects the
checkout's sources explicitly. No PowerShell or Bash wrapper is needed. Python
suites use Git for repository fixtures. Native suites additionally need CMake
and the chosen build tool, such as MSBuild, Ninja or Make. The CI matrix covers
Windows and Linux.

```text
python tools/test.py
python tools/test.py --suite python
python tools/test.py --suite checks
python tools/test.py --suite checks --format --history
```

The default runs all tests this product has. Core and Studio also build and run
their native tests with CMake and a host C++ compiler. The Kit and Disassembler
have Python suites. `--suite python` needs no compiler or Qt. Repository guards
and formatting are separate opt-in checks. The test runner explicitly excludes
the PowerShell formatter, so it never probes or starts PowerShell. The other
formatters retain their own language-specific tools; the separate `make format`
command still supports PowerShell files. A private stop-word list comes from
`RETROLARIUM_STOPWORDS`, an ancestor `.stopwords`, or CI's `STOPWORDS_LIST`. A
missing unconfigured list is reported as skipped; a configured missing file
fails. `--history` still checks historical objects.

Native test failures and timeouts fail the command. Missing game fixtures and a
test's exit code 77 count as skips, never passes. Missing executables or tracked
repository fixtures are failures. `--game-sources PATH` selects the prepared
game repositories; paths with spaces work without shell quoting inside the
runner. `--jobs`, `--config` and `--build-dir` control CMake. Windows, POSIX and
filesystem-specific assertions still run on their own platforms; the common
runner does not pretend another host has those APIs.

```text
python tools/test.py --suite native
python tools/test.py --suite native --bin path/to/existing/test-binaries
```

`--bin` runs an existing `tests.json` suite without rebuilding. Core's native
suite includes the real Python-to-rlcore round trips. Studio needs Qt 5.15 Core,
Gui, Widgets, Svg and LinguistTools; `--qt-prefix PATH` selects its SDK and
supplies Qt's DLL/plugin paths. A native headless Linux Studio run uses Qt's
offscreen plugin. Windows retains the Windows platform plugin.
