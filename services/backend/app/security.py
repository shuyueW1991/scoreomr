"""Passwords, tokens, IP privacy and small validation helpers."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import secrets
from typing import Iterable

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

# 32 MiB / 2 iterations is a deliberate trade-off for a 2-4 GB server: still
# expensive for offline cracking, but many concurrent logins cannot exhaust RAM.
_hasher = PasswordHasher(time_cost=2, memory_cost=32768, parallelism=2, hash_len=32, salt_len=16)
_DUMMY_HASH = _hasher.hash("scoreomr-dummy-password")

EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")


def normalize_email(value: str) -> str:
    return value.strip().lower()


def valid_email(value: str) -> bool:
    return bool(value) and len(value) <= 254 and bool(EMAIL_RE.match(value))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-ish behaviour for unknown users: always run a hash check."""
    try:
        return _hasher.verify(stored or _DUMMY_HASH, password)
    except (VerifyMismatchError, VerificationError, ValueError):
        return False


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_ip(secret: str, ip: str) -> str:
    return hmac.new(secret.encode("utf-8"), ip.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def client_ip_from_headers(peer: str, forwarded: Iterable[str], trust_proxy: bool) -> str:
    """Return a normalised client IP.

    Nginx is configured to *overwrite* X-Forwarded-For with $remote_addr, so the
    first entry is authoritative when the proxy is trusted.  Direct clients can
    spoof the header, which is why the API port is never published.
    """
    if trust_proxy:
        for value in forwarded:
            candidate = (value or "").split(",")[0].strip()
            if candidate:
                try:
                    return str(ipaddress.ip_address(candidate))
                except ValueError:
                    continue
    try:
        return str(ipaddress.ip_address(peer))
    except ValueError:
        return peer or "unknown"


def safe_next(value: str | None) -> str:
    if (
        not value
        or not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
    ):
        return "/"
    return value[:500]
