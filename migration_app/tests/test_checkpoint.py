import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from checkpoint import append_checkpoint, clear_checkpoint, load_checkpoint


class TestCheckpoint(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tmpdir.name) / "checkpoint.txt"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_missing_file_loads_as_empty_set(self):
        self.assertEqual(load_checkpoint(self.path), set())

    def test_append_then_load_roundtrip(self):
        append_checkpoint("005930", self.path)
        append_checkpoint("000660", self.path)
        self.assertEqual(load_checkpoint(self.path), {"005930", "000660"})

    def test_append_creates_parent_directory(self):
        nested = Path(self._tmpdir.name) / "nested" / "checkpoint.txt"
        append_checkpoint("005930", nested)
        self.assertEqual(load_checkpoint(nested), {"005930"})

    def test_clear_removes_file(self):
        append_checkpoint("005930", self.path)
        clear_checkpoint(self.path)
        self.assertEqual(load_checkpoint(self.path), set())

    def test_clear_missing_file_is_a_noop(self):
        clear_checkpoint(self.path)  # must not raise


if __name__ == "__main__":
    unittest.main()
