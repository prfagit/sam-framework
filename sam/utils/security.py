"""Security utilities and hardening for SAM framework."""

import hashlib
import hmac
import secrets
import re
import logging
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class SecurityConfig:
    """Security configuration settings."""

    max_request_size: int = 10 * 1024 * 1024  # 10MB
    max_string_length: int = 10000
    allowed_protocols: Optional[List[str]] = None
    blocked_domains: Optional[List[str]] = None
    rate_limit_bypass_tokens: Optional[List[str]] = None

    def __post_init__(self):
        if self.allowed_protocols is None:
            self.allowed_protocols = ["https", "wss"]
        if self.blocked_domains is None:
            self.blocked_domains = []
        if self.rate_limit_bypass_tokens is None:
            self.rate_limit_bypass_tokens = []


class InputValidator:
    """Comprehensive input validation and sanitization."""

    def __init__(self, config: Optional[SecurityConfig] = None):
        self.config = config or SecurityConfig()

        # Common patterns for validation
        self.solana_address_pattern = re.compile(r"^[A-HJ-NP-Z1-9]{32,44}$")
        self.solana_signature_pattern = re.compile(r"^[A-HJ-NP-Z1-9]{87,88}$")
        self.email_pattern = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

        # Dangerous patterns to block
        self.dangerous_patterns = [
            re.compile(r"<script[^>]*>", re.IGNORECASE),
            re.compile(r"javascript:", re.IGNORECASE),
            re.compile(r"vbscript:", re.IGNORECASE),
            re.compile(r"onload\s*=", re.IGNORECASE),
            re.compile(r"onerror\s*=", re.IGNORECASE),
            re.compile(r"eval\s*\(", re.IGNORECASE),
            re.compile(r"expression\s*\(", re.IGNORECASE),
        ]

    def validate_solana_address(self, address: str) -> bool:
        """Validate Solana wallet address format."""
        if not isinstance(address, str):
            return False

        if len(address) < 32 or len(address) > 44:
            return False

        return bool(self.solana_address_pattern.match(address))

    def validate_solana_signature(self, signature: str) -> bool:
        """Validate Solana transaction signature format."""
        if not isinstance(signature, str):
            return False

        return bool(self.solana_signature_pattern.match(signature))

    def validate_amount(
        self, amount: Union[int, float, str], min_val: float = 0.0, max_val: float = 1000.0
    ) -> bool:
        """Validate transaction amount."""
        try:
            amount_float = float(amount)
            return min_val <= amount_float <= max_val
        except (ValueError, TypeError):
            return False

    def validate_url(self, url: str) -> bool:
        """Validate URL format and security."""
        if not isinstance(url, str) or len(url) > 2048:
            return False

        try:
            parsed = urlparse(url)

            # Check protocol
            allowed_protocols = self.config.allowed_protocols or []
            if parsed.scheme not in allowed_protocols:
                logger.warning(f"Blocked URL with disallowed protocol: {parsed.scheme}")
                return False

            # Check domain blacklist
            blocked_domains = self.config.blocked_domains or []
            if parsed.hostname and any(
                blocked in parsed.hostname.lower() for blocked in blocked_domains
            ):
                logger.warning(f"Blocked URL with blacklisted domain: {parsed.hostname}")
                return False

            return True

        except Exception as e:
            logger.error(f"URL validation error: {e}")
            return False

    def sanitize_string(self, text: str, max_length: Optional[int] = None) -> str:
        """Sanitize string input by removing dangerous content."""
        if not isinstance(text, str):
            return ""

        # Apply length limit
        max_len = max_length or self.config.max_string_length
        if len(text) > max_len:
            text = text[:max_len]

        # Remove dangerous patterns
        for pattern in self.dangerous_patterns:
            text = pattern.sub("", text)

        # Remove null bytes and control characters
        text = "".join(char for char in text if ord(char) >= 32 or char in "\n\r\t")

        return text.strip()

    def validate_json_structure(
        self, data: Dict[str, Any], allowed_keys: Optional[List[str]] = None
    ) -> bool:
        """Validate JSON structure and keys."""
        if not isinstance(data, dict):
            return False

        # Check for oversized data
        try:
            import json

            json_str = json.dumps(data)
            if len(json_str) > self.config.max_request_size:
                logger.warning(f"Rejected oversized JSON: {len(json_str)} bytes")
                return False
        except Exception:
            return False

        # Check allowed keys if specified
        if allowed_keys:
            for key in data.keys():
                if key not in allowed_keys:
                    logger.warning(f"Rejected JSON with disallowed key: {key}")
                    return False

        return True

    def validate_private_key(self, private_key: str) -> bool:
        """Validate private key format (basic check)."""
        if not isinstance(private_key, str):
            return False

        # Basic length and character checks
        if len(private_key) < 32:
            return False

        # Should not contain obvious patterns
        if private_key.lower() in ["test", "example", "123", "password"]:
            return False

        return True


class SecurityScanner:
    """Security scanning and threat detection."""

    def __init__(self):
        self.suspicious_patterns = [
            # Common attack patterns
            re.compile(r"union\s+select", re.IGNORECASE),
            re.compile(r"drop\s+table", re.IGNORECASE),
            re.compile(r"exec\s*\(", re.IGNORECASE),
            re.compile(r"system\s*\(", re.IGNORECASE),
            re.compile(r"curl\s+", re.IGNORECASE),
            re.compile(r"wget\s+", re.IGNORECASE),
            re.compile(r"rm\s+-rf", re.IGNORECASE),
            re.compile(r"../../../", re.IGNORECASE),
            # Crypto-specific patterns
            re.compile(r"privateKey\s*[:=]", re.IGNORECASE),
            re.compile(r"mnemonic\s*[:=]", re.IGNORECASE),
            re.compile(r"seed\s*phrase", re.IGNORECASE),
        ]

    def scan_input(self, text: str) -> List[str]:
        """Scan input for suspicious patterns."""
        threats = []

        for pattern in self.suspicious_patterns:
            if pattern.search(text):
                threats.append(f"Suspicious pattern detected: {pattern.pattern}")

        return threats

    def scan_request_headers(self, headers: Dict[str, str]) -> List[str]:
        """Scan HTTP headers for security issues."""
        threats = []

        # Check for suspicious user agents
        user_agent = headers.get("User-Agent", "").lower()
        suspicious_agents = ["bot", "crawler", "scanner", "exploit"]
        if any(agent in user_agent for agent in suspicious_agents):
            threats.append(f"Suspicious User-Agent: {user_agent[:50]}...")

        # Check for unusual headers
        dangerous_headers = ["X-Forwarded-Host", "X-Original-URL", "X-Rewrite-URL"]
        for header in dangerous_headers:
            if header.lower() in [h.lower() for h in headers.keys()]:
                threats.append(f"Potentially dangerous header: {header}")

        return threats


class SecureLogger:
    """Security-focused logging that redacts sensitive information."""

    def __init__(self, logger_name: str):
        self.logger = logging.getLogger(logger_name)

        # Patterns to redact in logs
        self.redact_patterns = [
            (
                re.compile(
                    r'(private[_-]?key["\s]*[:=]["\s]*)([A-Za-z0-9+/=]{32,})(["\s]*)', re.IGNORECASE
                ),
                r"\1***REDACTED***\3",
            ),
            (
                re.compile(
                    r'(api[_-]?key["\s]*[:=]["\s]*)([A-Za-z0-9_-]{20,})(["\s]*)', re.IGNORECASE
                ),
                r"\1***REDACTED***\3",
            ),
            (
                re.compile(r'(token["\s]*[:=]["\s]*)([A-Za-z0-9._-]{20,})(["\s]*)', re.IGNORECASE),
                r"\1***REDACTED***\3",
            ),
            (
                re.compile(r'(password["\s]*[:=]["\s]*)([^\s"]+)(["\s]*)', re.IGNORECASE),
                r"\1***REDACTED***\3",
            ),
            (
                re.compile(r"([A-HJ-NP-Z1-9]{32,44})", re.IGNORECASE),
                lambda m: f"{m.group(1)[:8]}...{m.group(1)[-4:]}",
            ),  # Partial wallet addresses
        ]

    def redact_sensitive_data(self, message: str) -> str:
        """Redact sensitive data from log message."""
        for pattern, replacement in self.redact_patterns:
            if callable(replacement):
                message = pattern.sub(replacement, message)
            else:
                message = pattern.sub(str(replacement), message)

        return message

    def secure_log(self, level: int, message: str, *args, **kwargs):
        """Log message with sensitive data redaction."""
        redacted_message = self.redact_sensitive_data(message)
        self.logger.log(level, redacted_message, *args, **kwargs)

    def secure_info(self, message: str, *args, **kwargs):
        """Secure info logging."""
        self.secure_log(logging.INFO, message, *args, **kwargs)

    def secure_warning(self, message: str, *args, **kwargs):
        """Secure warning logging."""
        self.secure_log(logging.WARNING, message, *args, **kwargs)

    def secure_error(self, message: str, *args, **kwargs):
        """Secure error logging."""
        self.secure_log(logging.ERROR, message, *args, **kwargs)


class SecurityMiddleware:
    """Security middleware for request processing."""

    def __init__(self, config: Optional[SecurityConfig] = None):
        self.config = config or SecurityConfig()
        self.validator = InputValidator(config)
        self.scanner = SecurityScanner()
        self.secure_logger = SecureLogger("sam.security")

        # Rate limiting for security events
        self.security_violations: Dict[str, int] = {}

    async def validate_request(self, request_data: Dict[str, Any]) -> tuple[bool, List[str]]:
        """Validate incoming request for security issues."""
        issues = []

        # Size check
        try:
            import json

            request_size = len(json.dumps(request_data))
            if request_size > self.config.max_request_size:
                issues.append(f"Request too large: {request_size} bytes")
        except Exception:
            issues.append("Invalid request format")

        # Scan for threats in all string values
        def scan_recursive(obj, path=""):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    scan_recursive(value, f"{path}.{key}")
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    scan_recursive(item, f"{path}[{i}]")
            elif isinstance(obj, str):
                threats = self.scanner.scan_input(obj)
                if threats:
                    issues.extend([f"At {path}: {threat}" for threat in threats])

        scan_recursive(request_data)

        # Log security issues
        if issues:
            self.secure_logger.secure_warning(f"Security validation failed: {issues}")

        return len(issues) == 0, issues

    def generate_request_id(self) -> str:
        """Generate secure request ID for tracking."""
        return secrets.token_urlsafe(16)

    def generate_api_key(self, length: int = 32) -> str:
        """Generate cryptographically secure API key."""
        return secrets.token_urlsafe(length)

    def verify_integrity(self, data: str, signature: str, secret: str) -> bool:
        """Verify HMAC signature for data integrity."""
        try:
            expected_signature = hmac.new(
                secret.encode("utf-8"), data.encode("utf-8"), hashlib.sha256
            ).hexdigest()

            return hmac.compare_digest(signature, expected_signature)
        except Exception as e:
            self.secure_logger.secure_error(f"Integrity verification failed: {e}")
            return False

    def hash_sensitive_data(self, data: str, salt: Optional[str] = None) -> str:
        """Hash sensitive data with salt."""
        if salt is None:
            salt = secrets.token_hex(16)

        return hashlib.pbkdf2_hmac(
            "sha256",
            data.encode("utf-8"),
            salt.encode("utf-8"),
            100000,  # 100k iterations
        ).hex()


# Global security middleware instance
_security_middleware: Optional[SecurityMiddleware] = None


def get_security_middleware(config: Optional[SecurityConfig] = None) -> SecurityMiddleware:
    """Get global security middleware instance."""
    global _security_middleware

    if _security_middleware is None:
        _security_middleware = SecurityMiddleware(config)

    return _security_middleware


# Security decorator for functions
def security_check(
    validate_input: bool = True, log_access: bool = True, require_auth: bool = False
):
    """Security decorator for function calls."""

    def decorator(func):
        async def async_wrapper(*args, **kwargs):
            middleware = get_security_middleware()

            if log_access:
                middleware.secure_logger.secure_info(
                    f"Function access: {func.__name__} called with {len(args)} args"
                )

            if validate_input and kwargs:
                valid, issues = await middleware.validate_request(kwargs)
                if not valid:
                    raise ValueError(f"Security validation failed: {issues}")

            return await func(*args, **kwargs)

        def sync_wrapper(*args, **kwargs):
            middleware = get_security_middleware()

            if log_access:
                middleware.secure_logger.secure_info(
                    f"Function access: {func.__name__} called with {len(args)} args"
                )

            return func(*args, **kwargs)

        import asyncio

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator
