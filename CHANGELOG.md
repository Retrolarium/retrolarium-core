# Changelog

## Unreleased

- Refuse Enigma maps beyond the decoder's 64 KiB limit and validate redundant
  Nemesis code tables without quadratic work in the number of duplicates.
- Preserve Unicode Git-hook paths with explicit UTF-8 transport. Exercise real
  codec commands with non-ASCII paths, spaces and codec-error exit codes.
- Harden codec bounds, container contracts and atomic CLI writes. Keep Mega
  Drive compression in the shared C++ implementation.
- Run Python/native tests through one portable runner, checking CTest command
  arguments and expected exit codes. Share formatters and repository guards.

## 0.5.0

Tagged baseline:
[v0.5.0](https://github.com/Retrolarium/retrolarium-core/tree/v0.5.0).
