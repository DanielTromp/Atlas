"""Shared password hashing utilities for authentication flows."""
from __future__ import annotations

from passlib.context import CryptContext

try:  # pragma: no cover - handled during import
    import bcrypt as _bcrypt

    if not hasattr(_bcrypt, "__about__"):
        class _BcryptAbout:
            __version__ = getattr(_bcrypt, "__version__", "")

        _bcrypt.__about__ = _BcryptAbout()  # type: ignore[attr-defined]
except Exception:  # pragma: no cover - optional dependency state
    _bcrypt = None  # type: ignore[assignment]

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return _pwd_context.verify(password, password_hash)
    except Exception:
        return False


__all__ = ["hash_password", "verify_password"]
