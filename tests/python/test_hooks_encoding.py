"""Git's UTF-8 paths survive a non-ASCII absolute hooks directory."""

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from retrolarium_core import hooks


class HooksPathTest(unittest.TestCase):
    def test_real_git_absolute_unicode_hooks_path(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "repository \u0442\u0435\u0441\u0442"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            destination = root / "hooks \u043a\u0440\u044e\u0447\u043a\u0438"
            original = hooks._git
            # Explicit -c isolates this test from inherited core.hooksPath.
            with mock.patch.object(
                hooks,
                "_git",
                side_effect=lambda repo, *args: original(repo, "-c", f"core.hooksPath={destination}", *args),
            ):
                written = hooks.install(root)
            self.assertEqual({destination / name for name in hooks.HOOKS}, set(written))
            for name in hooks.HOOKS:
                self.assertIn(hooks.MARKER, (destination / name).read_text(encoding="utf-8"))
