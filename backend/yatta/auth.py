"""Access key (standard library only).

Opening https://<host>/?key=<key> once, or typing the key on the sign-in page, gives that browser a signed
session cookie valid for 30 days. Create a new random key, or set your own, with:

    python -m yatta.auth            # prints a new random key and link
    python -m yatta.auth --key XYZ  # use your own key

A new key signs every browser out. The key's scrypt hash and the session-signing secret live in
``settings.auth_file`` (default ~/.config/yatta/auth.json, mode 600), outside the repository.
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from pathlib import Path

from yatta.config import settings

AUTH_FILE = settings.auth_file
COOKIE = "yatta_session"
SESSION_SECONDS = 30 * 24 * 3600
SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)
    return {"salt": salt.hex(), "hash": digest.hex()}


def verify_password(password, record):
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(record["salt"]), **SCRYPT)
    return hmac.compare_digest(digest.hex(), record["hash"])


def make_token(secret, now=None, lifetime=SESSION_SECONDS):
    expires = int((now or time.time()) + lifetime)
    signature = hmac.new(bytes.fromhex(secret), str(expires).encode(), hashlib.sha256).digest()
    return f"{expires}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"


def verify_token(secret, token, now=None):
    try:
        expires, signature = token.split(".", 1)
        expected = make_token(secret, now=int(expires) - SESSION_SECONDS)
        return hmac.compare_digest(expected, f"{expires}.{signature}") and int(expires) > (now or time.time())
    except (ValueError, AttributeError):
        return False


def client_id(request):
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")


def signed_in(request):
    config = load()
    token = request.cookies.get(COOKIE)
    return bool(config and token and verify_token(config["secret"], token))


def set_session(response, request, config):
    secure = (request.headers.get("host") or "").rsplit(":", 1)[0] not in ("localhost", "127.0.0.1")
    response.set_cookie(COOKIE, make_token(config["secret"]), max_age=SESSION_SECONDS,
                        httponly=True, samesite="lax", secure=secure, path="/")


def load(path=None):
    path = path or AUTH_FILE
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def save_password(password, path=None):
    """Store a new key hash and a fresh secret (which invalidates existing sessions)."""
    path = Path(path or AUTH_FILE)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"password": hash_password(password), "secret": secrets.token_hex(32)}))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


class Throttle:
    """At most ``limit`` failed logins per client in ``window`` seconds."""

    def __init__(self, limit=10, window=900):
        self.limit, self.window, self.failures = limit, window, {}

    def blocked(self, client, now=None):
        now = now or time.time()
        recent = [t for t in self.failures.get(client, []) if now - t < self.window]
        self.failures[client] = recent
        return len(recent) >= self.limit

    def fail(self, client, now=None):
        self.failures.setdefault(client, []).append(now or time.time())


def main():
    parser = argparse.ArgumentParser(description="Create or set the Avatar Studio access key.")
    parser.add_argument("--key", help="use this key instead of a random one (8+ characters)")
    parser.add_argument("--host", default=settings.canonical_host)
    args = parser.parse_args()
    key = args.key or secrets.token_urlsafe(9)
    if len(key) < 8:
        sys.exit("Use at least 8 characters.")
    save_password(key)
    print(f"Access key: {key}\nLink: https://{args.host}/?key={key}\n(saved to {AUTH_FILE}; other browsers are signed out)")


if __name__ == "__main__":
    main()
