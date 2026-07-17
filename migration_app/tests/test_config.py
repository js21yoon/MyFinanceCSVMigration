import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config as config_module
from config import Config, load_env, mask_secret


class TestMaskSecret(unittest.TestCase):
    def test_masks_middle_keeps_prefix_and_suffix(self):
        masked = mask_secret("abcdefghijklmnop", keep_prefix=3, keep_suffix=3)
        self.assertEqual(masked, "abc" + "*" * 10 + "nop")

    def test_short_value_fully_masked(self):
        self.assertEqual(mask_secret("ab", keep_prefix=3, keep_suffix=3), "**")


class TestLoadEnv(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_parses_env_file_in_base_dir(self):
        (self.dir / ".env").write_text(
            "SUPABASE_URL=https://example.supabase.co\nSUPABASE_SERVICE_ROLE_KEY=secretkey\n",
            encoding="utf-8",
        )
        original = config_module._base_dir
        config_module._base_dir = lambda: self.dir
        try:
            env = load_env()
        finally:
            config_module._base_dir = original
        self.assertEqual(env["SUPABASE_URL"], "https://example.supabase.co")
        self.assertEqual(env["SUPABASE_SERVICE_ROLE_KEY"], "secretkey")

    def test_missing_required_key_raises(self):
        (self.dir / ".env").write_text("SUPABASE_URL=https://example.supabase.co\n", encoding="utf-8")
        original = config_module._base_dir
        config_module._base_dir = lambda: self.dir
        try:
            with self.assertRaises(RuntimeError):
                load_env()
        finally:
            config_module._base_dir = original

    def test_no_env_file_anywhere_raises(self):
        original = config_module._base_dir
        config_module._base_dir = lambda: self.dir
        try:
            with self.assertRaises(FileNotFoundError):
                load_env()
        finally:
            config_module._base_dir = original


class TestFrozenBaseDir(unittest.TestCase):
    def test_frozen_uses_executable_directory_not_file_directory(self):
        fake_exe_dir = Path(tempfile.gettempdir()) / "fake_frozen_app"
        original_frozen = getattr(sys, "frozen", None)
        original_executable = sys.executable
        sys.frozen = True
        sys.executable = str(fake_exe_dir / "FinancialsMigrator.exe")
        try:
            base = config_module._base_dir()
        finally:
            if original_frozen is None:
                del sys.frozen
            else:
                sys.frozen = original_frozen
            sys.executable = original_executable
        self.assertEqual(base, fake_exe_dir)

    def test_non_frozen_uses_source_file_directory(self):
        self.assertFalse(getattr(sys, "frozen", False))
        base = config_module._base_dir()
        self.assertEqual(base, Path(config_module.__file__).resolve().parent)


class TestConfig(unittest.TestCase):
    def test_config_masks_key_in_repr(self):
        tmpdir = tempfile.TemporaryDirectory()
        try:
            d = Path(tmpdir.name)
            (d / ".env").write_text(
                "SUPABASE_URL=https://example.supabase.co\nSUPABASE_SERVICE_ROLE_KEY=verysecretvalue1234\n",
                encoding="utf-8",
            )
            original = config_module._base_dir
            config_module._base_dir = lambda: d
            try:
                cfg = Config()
                self.assertEqual(cfg.supabase_url, "https://example.supabase.co")
                self.assertNotIn("verysecretvalue1234", repr(cfg))
            finally:
                config_module._base_dir = original
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
