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

This is not hypothetical. In `flicky_src` the four modules
`scripts/formats/{nemesis,enigma}_{dec,enc}.py` are already used both by the
source build (`Makefile` → `build.unpack_data`) and by the graphics editor
(`authoring/graphics_studio_model.py`). They also show why there must be one
implementation: the packer takes the original compressed bytes as a reference
and returns them verbatim when the content did not change. Two independent
implementations would silently corrupt the bytes on a round trip.

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

From the root of this repository:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build
ctest --test-dir build --output-on-failure
python -m unittest discover -s tests/python
```

Retrolarium Studio adds the core with `add_subdirectory` from a
`retrolarium-core` checkout beside it, without the core's tests: run them here.

## Contents

| Module    | Purpose                                         |
| --------- | ----------------------------------------------- |
| `nemesis` | unpacking and repacking Mega Drive tile streams |
| `enigma`  | unpacking and packing Mega Drive tile maps      |

Repacking Nemesis needs a reference stream: the code table sits inside the
stream itself, so the encoder reuses the original's header and table instead of
inventing its own. That removes the one truly lossy decision in the format.
Unchanged content stays byte-identical through the pair: the caller compares the
unpacked content and returns the original bytes when it did not change.

Nemesis and Enigma exist only in C++, which the kit runs as `rlcore`. Their
corpora (`tests/fixtures/megadrive/*_golden.txt`) were written by Python
implementations ported independently from the Flicky disassembly, removed once
the C++ became the only one; they stay the frozen reference the C++ must match.

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
which looks for the binary in this order: `RETROLARIUM_CORE`, a payload inside
the wheel, the build tree of the current checkout, then `PATH`.

```sh
rlcore nemesis decompress art.nem art.bin
rlcore nemesis compress art.bin art.nem repacked.nem
rlcore enigma decompress map.eni map.bin
rlcore enigma compress map.bin map.eni
```

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
were not checked.

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

`make lint` checks the tree for stop words; `make format` formats the Markdown
with mdformat and mdformat-gfm (`pip install mdformat mdformat-gfm`), and
`make format-check` only reports.

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
