"""Write the golden corpora's streams as seed files for the fuzz targets.

    python fuzz/seed_corpus.py tests/fixtures/megadrive/nemesis_golden.txt build/seeds/nemesis
    python fuzz/seed_corpus.py tests/fixtures/megadrive/enigma_golden.txt build/seeds/enigma

Each `stream` and `reference` line becomes one file named after its case.
"""

from __future__ import annotations

from pathlib import Path
import sys


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    corpus, output = Path(argv[0]), Path(argv[1])
    output.mkdir(parents=True, exist_ok=True)
    name = "case"
    written = 0
    for line in corpus.read_text(encoding="utf-8-sig").splitlines():
        key, _, value = line.strip().partition(" ")
        if key in ("case", "encode-case"):
            name = value
        elif key in ("stream", "reference"):
            (output / f"{name}.{key}").write_bytes(bytes.fromhex(value))
            written += 1
    print(f"{written} seeds in {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
