"""Password hashing.

Uses pwdlib (actively maintained) instead of the abandoned passlib;
recommended() = Argon2id with automatic fallback to bcrypt.
"""
from pwdlib import PasswordHash

password_hasher = PasswordHash.recommended()


def hash_password(plain: str) -> str:
    """Hash a plaintext password for storage."""
    return password_hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> tuple[bool, str | None]:
    """Verify a password against its stored hash.

    Returns ``(is_valid, updated_hash)`` — ``updated_hash`` is not None when
    the stored hash uses outdated parameters and should be re-saved.
    """
    try:
        return password_hasher.verify_and_update(plain, hashed)
    except Exception:  # malformed hash in DB — treat as mismatch
        return False, None
