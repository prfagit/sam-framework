"""Password policy validation utilities."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Cache for loaded common passwords
_COMMON_PASSWORDS_CACHE: Optional[Set[str]] = None


def _load_common_passwords() -> Set[str]:
    """Load common passwords from the bundled file.

    Returns:
        Set of common passwords (lowercase)
    """
    global _COMMON_PASSWORDS_CACHE

    if _COMMON_PASSWORDS_CACHE is not None:
        return _COMMON_PASSWORDS_CACHE

    passwords: Set[str] = set()

    # Try to load from the bundled file
    passwords_file = Path(__file__).parent / "common_passwords.txt"

    if passwords_file.exists():
        try:
            with open(passwords_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if line and not line.startswith("#"):
                        passwords.add(line.lower())
            logger.debug("Loaded %d common passwords from %s", len(passwords), passwords_file)
        except Exception as e:
            logger.warning("Failed to load common passwords file: %s", e)
    else:
        logger.warning("Common passwords file not found: %s", passwords_file)

    # Add some essential fallbacks if file is missing or empty
    if len(passwords) < 100:
        fallback_passwords = {
            "password",
            "password123",
            "123456",
            "12345678",
            "qwerty",
            "abc123",
            "monkey",
            "letmein",
            "trustno1",
            "dragon",
            "baseball",
            "iloveyou",
            "master",
            "sunshine",
            "ashley",
            "bailey",
            "passw0rd",
            "shadow",
            "123123",
            "654321",
            "superman",
            "qazwsx",
            "michael",
            "football",
            "admin",
            "root",
            "test",
            "guest",
            "changeme",
            "welcome",
        }
        passwords.update(fallback_passwords)

    _COMMON_PASSWORDS_CACHE = passwords
    return passwords


class PasswordPolicy:
    """Password policy configuration and validation."""

    def __init__(
        self,
        min_length: int = 8,
        require_uppercase: bool = True,
        require_lowercase: bool = True,
        require_digits: bool = True,
        require_special: bool = False,
        max_length: int = 128,
        common_passwords: List[str] | None = None,
    ):
        """
        Initialize password policy.

        Args:
            min_length: Minimum password length (default: 8)
            require_uppercase: Require at least one uppercase letter (default: True)
            require_lowercase: Require at least one lowercase letter (default: True)
            require_digits: Require at least one digit (default: True)
            require_special: Require at least one special character (default: False)
            max_length: Maximum password length (default: 128)
            common_passwords: List of common passwords to reject. If None, loads from
                common_passwords.txt file. Pass empty list to disable check.
        """
        self.min_length = min_length
        self.require_uppercase = require_uppercase
        self.require_lowercase = require_lowercase
        self.require_digits = require_digits
        self.require_special = require_special
        self.max_length = max_length
        # If None, load from file; if empty list, disable; otherwise use provided list
        if common_passwords is None:
            self.common_passwords = _load_common_passwords()
        else:
            self.common_passwords = set(p.lower() for p in common_passwords)

    def validate(self, password: str) -> Tuple[bool, List[str]]:
        """
        Validate a password against the policy.

        Args:
            password: Password to validate

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors: List[str] = []

        if not isinstance(password, str):
            return False, ["Password must be a string"]

        # Length checks
        if len(password) < self.min_length:
            errors.append(f"Password must be at least {self.min_length} characters long")
        if len(password) > self.max_length:
            errors.append(f"Password must be no more than {self.max_length} characters long")

        # Character requirements
        if self.require_uppercase and not re.search(r"[A-Z]", password):
            errors.append("Password must contain at least one uppercase letter")

        if self.require_lowercase and not re.search(r"[a-z]", password):
            errors.append("Password must contain at least one lowercase letter")

        if self.require_digits and not re.search(r"\d", password):
            errors.append("Password must contain at least one digit")

        if self.require_special and not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            errors.append("Password must contain at least one special character")

        # Check against common passwords
        if self.common_passwords and password.lower() in self.common_passwords:
            errors.append("Password is too common and easily guessable")

        # Check for common patterns
        if re.search(r"(.)\1{3,}", password):  # Same character repeated 4+ times
            errors.append("Password contains too many repeated characters")

        if re.search(r"(012|123|234|345|456|567|678|789|890)", password):
            errors.append("Password contains sequential digits")

        if re.search(
            r"(abc|bcd|cde|def|efg|fgh|ghi|hij|ijk|jkl|klm|lmn|mno|nop|opq|pqr|qrs|rst|stu|tuv|uvw|vwx|wxy|xyz)",
            password.lower(),
        ):
            errors.append("Password contains sequential letters")

        return len(errors) == 0, errors


# Default password policy (moderate security)
# Common passwords are loaded lazily from common_passwords.txt
DEFAULT_PASSWORD_POLICY = PasswordPolicy(
    min_length=8,
    require_uppercase=True,
    require_lowercase=True,
    require_digits=True,
    require_special=False,  # Not required by default for better UX
    max_length=128,
    common_passwords=None,  # Will load from file on first validation
)


def validate_password(
    password: str, policy: PasswordPolicy | None = None
) -> Tuple[bool, List[str]]:
    """
    Validate a password against the default or provided policy.

    Args:
        password: Password to validate
        policy: Optional custom policy (uses DEFAULT_PASSWORD_POLICY if not provided)

    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    if policy is None:
        policy = DEFAULT_PASSWORD_POLICY
    return policy.validate(password)


__all__ = ["PasswordPolicy", "DEFAULT_PASSWORD_POLICY", "validate_password"]
