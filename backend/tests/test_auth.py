import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
from yatta import auth  # noqa: E402


class StudioAuthTests(unittest.TestCase):
    def test_password_hash_round_trip(self):
        record = auth.hash_password("correct horse battery")
        self.assertTrue(auth.verify_password("correct horse battery", record))
        self.assertFalse(auth.verify_password("correct horse batterY", record))
        self.assertNotEqual(auth.hash_password("same")["hash"], auth.hash_password("same")["hash"])  # salted

    def test_tokens_expire_and_resist_tampering(self):
        secret = "ab" * 32
        token = auth.make_token(secret, now=1000)
        self.assertTrue(auth.verify_token(secret, token, now=2000))
        self.assertFalse(auth.verify_token(secret, token, now=1000 + auth.SESSION_SECONDS + 1))
        self.assertFalse(auth.verify_token("cd" * 32, token, now=2000))
        expires, signature = token.split(".")
        self.assertFalse(auth.verify_token(secret, f"{int(expires) + 999}.{signature}", now=2000))
        for junk in ("", "abc", "1.2.3", None):
            self.assertFalse(auth.verify_token(secret, junk, now=2000))

    def test_save_password_writes_private_file_and_rotates_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "conf" / "auth.json"
            auth.save_password("first password", path)
            first = json.loads(path.read_text())
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertTrue(auth.verify_password("first password", first["password"]))
            auth.save_password("second password", path)
            self.assertNotEqual(json.loads(path.read_text())["secret"], first["secret"])

    def test_throttle(self):
        throttle = auth.Throttle(limit=3, window=60)
        for t in (0, 1, 2):
            self.assertFalse(throttle.blocked("ip", now=t))
            throttle.fail("ip", now=t)
        self.assertTrue(throttle.blocked("ip", now=3))
        self.assertFalse(throttle.blocked("other", now=3))
        self.assertFalse(throttle.blocked("ip", now=100))


if __name__ == "__main__":
    unittest.main()
