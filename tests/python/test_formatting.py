import subprocess
import tempfile
import unittest
from pathlib import Path

from retrolarium_core import formatting


class FilesForTests(unittest.TestCase):
    def test_third_party_trees_and_formatignore_paths_are_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            for name in (
                "a.py",
                "third_party/b.py",
                "tools/third_party/c.py",
                "archive/d.py",
                "games/e.md",
                "games/f.py",
                "config/records.json",
                "config/kept.json",
            ):
                (repo / name).parent.mkdir(parents=True, exist_ok=True)
                (repo / name).write_text("x = 1\n", encoding="utf-8")
            (repo / ".formatignore").write_text(
                "# frozen\narchive/\ngames/*.py\nconfig/records.json\n", encoding="utf-8"
            )
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)

            self.assertEqual(["a.py"], formatting.files_for(repo, ("*.py",)))
            self.assertEqual(["games/e.md"], formatting.files_for(repo, ("*.md",)))
            self.assertEqual(["config/kept.json"], formatting.files_for(repo, ("*.json",)))


if __name__ == "__main__":
    unittest.main()
