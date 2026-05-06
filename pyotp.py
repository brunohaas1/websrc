from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time
from urllib.parse import quote


def random_base32(length: int = 32) -> str:
    raw = base64.b32encode(os.urandom(max(10, length))).decode("ascii").rstrip("=")
    return raw[:length]


class TOTP:
    def __init__(self, secret: str, interval: int = 30, digits: int = 6):
        self.secret = (secret or "").strip().replace(" ", "")
        self.interval = max(10, int(interval))
        self.digits = max(6, int(digits))

    def _normalize_secret(self) -> bytes:
        value = self.secret.upper()
        pad = "=" * ((8 - len(value) % 8) % 8)
        return base64.b32decode(value + pad, casefold=True)

    def _at_counter(self, counter: int) -> str:
        key = self._normalize_secret()
        msg = struct.pack(">Q", int(counter))
        digest = hmac.new(key, msg, hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
        return str(code % (10 ** self.digits)).zfill(self.digits)

    def now(self) -> str:
        counter = int(time.time() // self.interval)
        return self._at_counter(counter)

    def verify(self, token: str, valid_window: int = 0) -> bool:
        token = str(token or "").strip()
        if not token or not token.isdigit():
            return False
        base_counter = int(time.time() // self.interval)
        window = max(0, int(valid_window))
        for shift in range(-window, window + 1):
            if hmac.compare_digest(token, self._at_counter(base_counter + shift)):
                return True
        return False

    def provisioning_uri(self, name: str, issuer_name: str | None = None) -> str:
        label = quote(name or "user")
        issuer = quote(issuer_name or "app")
        return (
            f"otpauth://totp/{issuer}:{label}?secret={self.secret}"
            f"&issuer={issuer}&period={self.interval}&digits={self.digits}"
        )
