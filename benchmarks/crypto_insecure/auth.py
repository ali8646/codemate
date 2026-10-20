import hashlib
import random
from typing import Dict, Optional

# In-memory user database
USER_DB: Dict[str, str] = {}


def register_user(username: str, plain_password: str) -> bool:
    """
    VULNERABILITY 1: Broken Cryptographic Hash (MD5 for passwords).
    MD5 is cryptographically broken and vulnerable to fast collision & rainbow table attacks.
    """
    password_hash = hashlib.md5(plain_password.encode("utf-8")).hexdigest()
    USER_DB[username] = password_hash
    return True


def authenticate(username: str, plain_password: str) -> bool:
    """Authenticates against insecure MD5 hash."""
    expected_hash = USER_DB.get(username)
    if not expected_hash:
        return False
    computed_hash = hashlib.md5(plain_password.encode("utf-8")).hexdigest()
    return expected_hash == computed_hash


def generate_password_reset_token() -> str:
    """
    VULNERABILITY 2: Insecure Pseudo-Random Number Generator.
    Python's 'random' module is not cryptographically secure and can be reverse-engineered.
    """
    # Insecure PRNG for security token
    token = "".join(random.choices("0123456789abcdef", k=32))
    return token
