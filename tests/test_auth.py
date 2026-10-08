import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from py_remote_input.auth import (
    AuthStore,
    InvalidPin,
    RateLimited,
    generate_pin,
    hash_token,
    load_pin,
)


class AuthStoreTests(unittest.TestCase):
    def test_correct_pin_issues_token(self):
        auth = AuthStore("482915")
        token = auth.authenticate("192.168.1.5", "482915")

        self.assertTrue(token)
        self.assertTrue(auth.validate(token, "192.168.1.5"))

    def test_token_is_valid_from_any_ip(self):
        # Phone LAN IPs change (DHCP, private Wi-Fi addresses); trust follows
        # the device token, not the IP.
        auth = AuthStore("482915")
        token = auth.authenticate("192.168.1.5", "482915")

        self.assertTrue(auth.validate(token, "10.0.0.9"))
        self.assertTrue(auth.validate(token, "192.168.1.77"))

    def test_wrong_pin_raises_and_unknown_token_rejected(self):
        auth = AuthStore("482915")
        with self.assertRaises(InvalidPin):
            auth.authenticate("192.168.1.5", "000000")
        self.assertFalse(auth.validate("not-a-real-token", "192.168.1.5"))

    def test_five_failures_trigger_rate_limit_then_success_resets(self):
        auth = AuthStore("482915")
        for _ in range(5):
            with self.assertRaises(InvalidPin):
                auth.authenticate("192.168.1.5", "111111")

        with self.assertRaises(RateLimited) as caught:
            auth.authenticate("192.168.1.5", "482915")
        self.assertGreaterEqual(caught.exception.retry_after, 1)

        # Other IPs are not affected by the lockout.
        token = auth.authenticate("192.168.1.6", "482915")
        self.assertTrue(auth.validate(token, "192.168.1.6"))

    def test_trusted_device_survives_restart_and_is_stored_hashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            trusted_path = Path(tmp) / "trusted_devices.json"
            auth = AuthStore("482915", trusted_path=trusted_path)
            token = auth.authenticate("192.168.1.5", "482915")
            self.assertEqual(auth.device_count, 1)

            # Only the SHA-256 hash is persisted, never the raw token.
            on_disk = trusted_path.read_text(encoding="utf-8")
            self.assertNotIn(token, on_disk)
            self.assertIn(hash_token(token), on_disk)
            self.assertEqual(oct(trusted_path.stat().st_mode & 0o777), "0o600")

            # Simulate a server restart: a brand new AuthStore reloads trust.
            reloaded = AuthStore("482915", trusted_path=trusted_path)
            self.assertTrue(reloaded.validate(token, "192.168.1.99"))

    def test_revoke_forgets_device(self):
        with tempfile.TemporaryDirectory() as tmp:
            trusted_path = Path(tmp) / "trusted_devices.json"
            auth = AuthStore("482915", trusted_path=trusted_path)
            token = auth.authenticate("192.168.1.5", "482915")
            self.assertTrue(auth.revoke(token))
            self.assertFalse(auth.validate(token, "192.168.1.5"))

            reloaded = AuthStore("482915", trusted_path=trusted_path)
            self.assertFalse(reloaded.validate(token, "192.168.1.5"))
            self.assertFalse(auth.revoke("unknown-token"))


class LoadPinTests(unittest.TestCase):
    def test_generate_pin_is_numeric(self):
        pin = generate_pin()
        self.assertEqual(len(pin), 6)
        self.assertTrue(pin.isdigit())

    def test_env_pin_takes_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with mock.patch.dict(os.environ, {"PIN_CODE": "135790"}, clear=True):
                pin, path, generated = load_pin(base)
            self.assertEqual(pin, "135790")
            self.assertFalse(generated)
            self.assertFalse(path.exists())

    def test_non_digit_env_pin_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"PIN_CODE": "secret"}, clear=True):
                with self.assertRaises(RuntimeError):
                    load_pin(Path(tmp))

    def test_generates_and_persists_pin_file_with_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with mock.patch.dict(os.environ, {}, clear=True):
                pin, path, generated = load_pin(base)
                self.assertTrue(generated)
                self.assertTrue(pin.isdigit())
                self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")

                pin_again, _, generated_again = load_pin(base)
                self.assertEqual(pin_again, pin)
                self.assertFalse(generated_again)


if __name__ == "__main__":
    unittest.main()
