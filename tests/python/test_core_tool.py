"""The Kit reaches the C++ core by running rlcore, not by linking to it.

These tests cover the locating rules and, when a built rlcore is available, a
real round trip through both compression codecs. The round-trip tests skip
rather than fail when the core has not been built, because a source checkout
without a build is a normal state, and a hard failure there would train people
to ignore the suite.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))

from retrolarium_core import tool as core_tool
from retrolarium_core.tool import CoreToolError


def available() -> Path | None:
    try:
        return core_tool.find_core_tool()
    except CoreToolError:
        return None


class FindCoreToolTest(unittest.TestCase):
    def test_environment_override_wins(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stand_in = Path(directory) / "rlcore-stand-in"
            stand_in.write_bytes(b"")
            previous = os.environ.get(core_tool.ENVIRONMENT_OVERRIDE)
            os.environ[core_tool.ENVIRONMENT_OVERRIDE] = str(stand_in)
            try:
                self.assertEqual(core_tool.find_core_tool(), stand_in)
            finally:
                if previous is None:
                    del os.environ[core_tool.ENVIRONMENT_OVERRIDE]
                else:
                    os.environ[core_tool.ENVIRONMENT_OVERRIDE] = previous

    def test_missing_override_is_reported_clearly(self) -> None:
        previous = os.environ.get(core_tool.ENVIRONMENT_OVERRIDE)
        os.environ[core_tool.ENVIRONMENT_OVERRIDE] = str(Path(tempfile.gettempdir()) / "definitely-not-here")
        try:
            with self.assertRaises(CoreToolError) as raised:
                core_tool.find_core_tool()
            self.assertIn(core_tool.ENVIRONMENT_OVERRIDE, str(raised.exception))
        finally:
            if previous is None:
                del os.environ[core_tool.ENVIRONMENT_OVERRIDE]
            else:
                os.environ[core_tool.ENVIRONMENT_OVERRIDE] = previous


def fake_rlcore(folder: Path, version: str, command: str = "sys.stdout.write('{\"size\": 0}')") -> Path:
    """An rlcore stand-in: a Python script that reports `version` and runs
    the statement `command` for any other command."""
    script = folder / "fake_rlcore.py"
    script.write_text(
        f"import sys, time\nif sys.argv[1:] == ['version']:\n    print({version!r})\nelse:\n    {command}\n",
        encoding="utf-8",
    )
    if os.name == "nt":
        launcher = folder / "rlcore.bat"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        launcher = folder / "rlcore"
        launcher.write_text(f"#!{sys.executable}\n" + script.read_text(encoding="utf-8"), encoding="utf-8")
        launcher.chmod(0o755)
    return launcher


class PinnedVersionTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        environment = mock.patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)

    def test_an_rlcore_of_another_version_is_refused(self) -> None:
        os.environ[core_tool.ENVIRONMENT_OVERRIDE] = str(fake_rlcore(self.folder, "0.0.1"))
        with self.assertRaises(CoreToolError) as raised:
            core_tool.run(["nemesis", "decompress", "a", "b"])
        message = str(raised.exception)
        self.assertIn("0.0.1", message)
        self.assertIn(core_tool.RLCORE_VERSION, message)
        self.assertIn(os.environ[core_tool.ENVIRONMENT_OVERRIDE], message)

    def test_an_rlcore_of_this_version_runs(self) -> None:
        os.environ[core_tool.ENVIRONMENT_OVERRIDE] = str(fake_rlcore(self.folder, core_tool.RLCORE_VERSION))
        self.assertEqual({"size": 0}, core_tool.run(["nemesis", "decompress", "a", "b"]))
        self.assertEqual(core_tool.RLCORE_VERSION, core_tool.version())


class FailureTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        environment = mock.patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)

    def use(self, command: str) -> None:
        os.environ[core_tool.ENVIRONMENT_OVERRIDE] = str(fake_rlcore(self.folder, core_tool.RLCORE_VERSION, command))

    def test_output_that_is_not_utf8_is_replaced_not_fatal(self) -> None:
        self.use('sys.stdout.buffer.write(b\'{"output": "\\xff"}\')')
        self.assertEqual({"output": "\ufffd"}, core_tool.run(["nemesis", "decompress", "a", "b"]))
        self.use("sys.stderr.buffer.write(b'cannot read \\xff.nem'); sys.exit(3)")
        with self.assertRaises(CoreToolError) as raised:
            core_tool.run(["nemesis", "decompress", "a", "b"])
        self.assertIn("exit code 3", str(raised.exception))
        self.assertIn("\ufffd.nem", str(raised.exception))

    def test_a_hung_rlcore_is_a_core_tool_error(self) -> None:
        self.use("time.sleep(5)")
        with self.assertRaises(CoreToolError) as raised:
            core_tool.run(["nemesis", "decompress", "a", "b"], timeout=1)
        self.assertIn("did not finish", str(raised.exception))

    @unittest.skipIf(os.name == "nt", "Windows runs any file it is handed")
    def test_an_rlcore_that_cannot_start_is_a_core_tool_error(self) -> None:
        stand_in = self.folder / "rlcore"
        stand_in.write_bytes(b"not a program")
        stand_in.chmod(0o644)
        os.environ[core_tool.ENVIRONMENT_OVERRIDE] = str(stand_in)
        with self.assertRaises(CoreToolError):
            core_tool.run(["version"])


class LookupOrderTest(unittest.TestCase):
    def setUp(self) -> None:
        environment = mock.patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop(core_tool.ENVIRONMENT_OVERRIDE, None)
        os.environ.pop(core_tool.DEVELOPMENT_SWITCH, None)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.build = Path(directory.name) / "build" / "rlcore"
        self.build.parent.mkdir()
        self.build.write_bytes(b"")
        for name, value in (("_packaged_candidates", lambda: []), ("_checkout_candidates", lambda: [self.build])):
            patcher = mock.patch.object(core_tool, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_build_tree_is_ignored_without_the_development_switch(self) -> None:
        with mock.patch.object(core_tool.shutil, "which", lambda name: None):
            with self.assertRaises(CoreToolError) as raised:
                core_tool.find_core_tool()
            self.assertIn(core_tool.DEVELOPMENT_SWITCH, str(raised.exception))
            os.environ[core_tool.DEVELOPMENT_SWITCH] = "1"
            self.assertEqual(self.build, core_tool.find_core_tool())

    def test_path_comes_before_a_build_tree(self) -> None:
        os.environ[core_tool.DEVELOPMENT_SWITCH] = "1"
        on_path = str(self.build.parent.parent / "rlcore-on-path")
        with mock.patch.object(core_tool.shutil, "which", lambda name: on_path):
            self.assertEqual(Path(on_path), core_tool.find_core_tool())


@unittest.skipIf(available() is None, "rlcore has not been built")
class CoreToolRoundTripTest(unittest.TestCase):
    def test_version_is_reported(self) -> None:
        self.assertRegex(core_tool.version(), r"^\d+\.\d+\.\d+$")

    def test_enigma_round_trip(self) -> None:
        words = list(range(0x100, 0x110)) + [0x0042] * 8
        plain = b"".join(bytes(((word >> 8) & 0xFF, word & 0xFF)) for word in words)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "plain.bin"
            packed = root / "packed.eni"
            restored = root / "restored.bin"
            source.write_bytes(plain)

            result = core_tool.enigma_compress(source, packed)
            self.assertEqual(result["size"], packed.stat().st_size)

            core_tool.enigma_decompress(packed, restored)
            self.assertEqual(restored.read_bytes(), plain)

    def test_nemesis_round_trip_uses_the_reference_table(self) -> None:
        # Nemesis cannot compress without a reference, because the code table
        # is part of the stream. This is one tile whose every nybble is 5,
        # from the Nemesis corpus.
        reference_bytes = bytes.fromhex("0001057200ff00000000")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.nem"
            reference.write_bytes(reference_bytes)
            decoded = root / "decoded.bin"

            core_tool.nemesis_decompress(reference, decoded)
            plain = decoded.read_bytes()
            self.assertEqual(len(plain), 32)

            repacked = root / "repacked.nem"
            core_tool.nemesis_compress(decoded, reference, repacked)

            restored = root / "restored.bin"
            core_tool.nemesis_decompress(repacked, restored)
            self.assertEqual(restored.read_bytes(), plain)

    def test_a_refused_command_raises(self) -> None:
        with self.assertRaises(CoreToolError):
            core_tool.run(["nemesis", "decompress"])


if __name__ == "__main__":
    unittest.main()
