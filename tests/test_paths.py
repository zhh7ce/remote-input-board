import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from py_remote_input import paths


class XdgDirectoryTests(unittest.TestCase):
    def test_defaults_follow_xdg_env(self):
        env = {"XDG_CONFIG_HOME": "/tmp/cfg", "XDG_DATA_HOME": "/tmp/data"}
        env.pop("REMOTE_INPUT_CONFIG_DIR", None)
        env.pop("REMOTE_INPUT_DATA_DIR", None)
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(paths.config_dir(), Path("/tmp/cfg") / paths.APP_NAME)
            self.assertEqual(paths.data_dir(), Path("/tmp/data") / paths.APP_NAME)

    def test_defaults_fall_back_to_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "HOME": tmp,
                "XDG_CONFIG_HOME": "",
                "XDG_DATA_HOME": "",
                "REMOTE_INPUT_CONFIG_DIR": "",
                "REMOTE_INPUT_DATA_DIR": "",
            }
            with mock.patch.dict(os.environ, env, clear=False):
                self.assertEqual(
                    paths.config_dir(),
                    Path(tmp) / ".config" / paths.APP_NAME,
                )
                self.assertEqual(
                    paths.data_dir(),
                    Path(tmp) / ".local" / "share" / paths.APP_NAME,
                )

    def test_explicit_overrides_beat_xdg(self):
        env = {
            "XDG_CONFIG_HOME": "/tmp/cfg",
            "XDG_DATA_HOME": "/tmp/data",
            "REMOTE_INPUT_CONFIG_DIR": "/var/tmp/mycfg",
            "REMOTE_INPUT_DATA_DIR": "/var/tmp/mydata",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(paths.config_dir(), Path("/var/tmp/mycfg"))
            self.assertEqual(paths.data_dir(), Path("/var/tmp/mydata"))


class EnsureAppDirsTests(unittest.TestCase):
    def test_creates_config_0700_and_data_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {
                "REMOTE_INPUT_CONFIG_DIR": str(root / "config"),
                "REMOTE_INPUT_DATA_DIR": str(root / "data"),
            }
            with mock.patch.dict(os.environ, env, clear=False):
                config, data = paths.ensure_app_dirs()

            self.assertTrue(config.is_dir())
            self.assertEqual(oct(config.stat().st_mode & 0o777), "0o700")
            self.assertTrue((data / "logs").is_dir())


class LegacyMigrationTests(unittest.TestCase):
    def _prepare(self) -> tuple[Path, Path, Path]:
        tmp = Path(tempfile.mkdtemp())
        legacy = tmp / "legacy"
        config = tmp / "config"
        data = tmp / "data"
        legacy.mkdir()
        (data / "logs").mkdir(parents=True)
        return legacy, config, data

    def test_moves_config_files_and_logs_when_pristine(self):
        legacy, config, data = self._prepare()
        (legacy / "pin.txt").write_text("123456\n")
        (legacy / "trusted_devices.json").write_text("[]")
        (legacy / "cert.pem").write_text("cert")
        (legacy / "key.pem").write_text("key")
        legacy_logs = legacy / "logs" / "history"
        legacy_logs.mkdir(parents=True)
        (legacy_logs / "x.log").write_text("{}")

        moved = paths.migrate_legacy_files(config, data, cwd=legacy)

        self.assertEqual((config / "pin.txt").read_text(), "123456\n")
        self.assertTrue((config / "trusted_devices.json").is_file())
        self.assertTrue((config / "cert.pem").is_file())
        self.assertTrue((config / "key.pem").is_file())
        self.assertEqual((data / "logs" / "history" / "x.log").read_text(), "{}")
        self.assertFalse(legacy_logs.exists())
        self.assertEqual(sorted(moved), ["cert.pem", "key.pem", "logs/", "pin.txt", "trusted_devices.json"])

    def test_does_not_touch_initialised_config(self):
        legacy, config, data = self._prepare()
        config.mkdir(parents=True)
        (config / "pin.txt").write_text("999999\n")
        (legacy / "pin.txt").write_text("123456\n")

        moved = paths.migrate_legacy_files(config, data, cwd=legacy)

        self.assertEqual(moved, [])
        self.assertEqual((config / "pin.txt").read_text(), "999999\n")
        self.assertTrue((legacy / "pin.txt").exists())

    def test_without_legacy_files_is_noop(self):
        legacy, config, data = self._prepare()

        self.assertEqual(paths.migrate_legacy_files(config, data, cwd=legacy), [])

    def test_skips_when_cwd_is_the_config_dir(self):
        legacy, _config, data = self._prepare()
        # Point "cwd" at the config target itself.
        target = legacy
        (target / "logs").mkdir(exist_ok=True)
        self.assertEqual(paths.migrate_legacy_files(target, data, cwd=target), [])


if __name__ == "__main__":
    unittest.main()
