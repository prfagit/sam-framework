"""Input sanitization utilities for user-provided content."""

from __future__ import annotations

import html
import re
from typing import Any, Dict, List

# Dangerous patterns that should be removed or escaped
DANGEROUS_PATTERNS = [
    re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL),
    re.compile(r"javascript:", re.IGNORECASE),
    re.compile(r"vbscript:", re.IGNORECASE),
    re.compile(r"onload\s*=", re.IGNORECASE),
    re.compile(r"onerror\s*=", re.IGNORECASE),
    re.compile(r"onclick\s*=", re.IGNORECASE),
    re.compile(r"onmouseover\s*=", re.IGNORECASE),
    re.compile(r"eval\s*\(", re.IGNORECASE),
    re.compile(r"expression\s*\(", re.IGNORECASE),
    re.compile(r"<iframe[^>]*>", re.IGNORECASE),
    re.compile(r"<object[^>]*>", re.IGNORECASE),
    re.compile(r"<embed[^>]*>", re.IGNORECASE),
]


def sanitize_string(text: str, max_length: int = 10000, allow_html: bool = False) -> str:
    """Sanitize a string input by removing dangerous content.

    Args:
        text: Input string to sanitize
        max_length: Maximum allowed length (default: 10000)
        allow_html: If True, escape HTML instead of removing it (default: False)

    Returns:
        Sanitized string
    """
    if not isinstance(text, str):
        return ""

    # Truncate if too long
    if len(text) > max_length:
        text = text[:max_length]

    # Remove dangerous patterns
    for pattern in DANGEROUS_PATTERNS:
        text = pattern.sub("", text)

    # Remove null bytes and control characters (except newlines and tabs)
    text = "".join(char for char in text if ord(char) >= 32 or char in "\n\r\t")

    # Escape HTML if not allowing it
    if not allow_html:
        text = html.escape(text)

    return text.strip()


def sanitize_message_content(content: str) -> str:
    """Sanitize message content for storage.

    This preserves markdown and basic formatting while removing XSS risks.

    Args:
        content: Message content to sanitize

    Returns:
        Sanitized content safe for storage and display
    """
    if not isinstance(content, str):
        return ""

    # Allow longer content for messages
    content = sanitize_string(content, max_length=50000, allow_html=False)

    # Remove any remaining script tags (double-check)
    content = re.sub(r"<script[^>]*>.*?</script>", "", content, flags=re.IGNORECASE | re.DOTALL)

    return content


def sanitize_username(username: str) -> str:
    """Sanitize username input.

    Args:
        username: Username to sanitize

    Returns:
        Sanitized username
    """
    if not isinstance(username, str):
        return ""

    # Remove dangerous characters, keep alphanumeric, underscore, dash, dot
    username = re.sub(r"[^a-zA-Z0-9_.-]", "", username)

    # Limit length
    username = username[:50]

    return username.strip().lower()


def sanitize_session_name(name: str) -> str:
    """Sanitize session name input.

    Args:
        name: Session name to sanitize

    Returns:
        Sanitized session name
    """
    if not isinstance(name, str):
        return ""

    # Allow more characters for session names (spaces, basic punctuation)
    name = sanitize_string(name, max_length=200, allow_html=False)

    # Remove leading/trailing whitespace
    name = name.strip()

    return name


def sanitize_message(message: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize a message dictionary.

    Args:
        message: Message dict with 'role' and 'content' keys

    Returns:
        Sanitized message dict
    """
    if not isinstance(message, dict):
        return {"role": "user", "content": ""}

    role = message.get("role", "user")
    if role not in ("user", "assistant", "system"):
        role = "user"

    content = message.get("content", "")
    if isinstance(content, str):
        content = sanitize_message_content(content)
    else:
        content = ""

    return {
        "role": role,
        "content": content,
    }


def sanitize_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sanitize a list of messages.

    Args:
        messages: List of message dicts

    Returns:
        List of sanitized message dicts
    """
    if not isinstance(messages, list):
        return []

    return [sanitize_message(msg) for msg in messages if isinstance(msg, dict)]


__all__ = [
    "sanitize_string",
    "sanitize_message_content",
    "sanitize_username",
    "sanitize_session_name",
    "sanitize_message",
    "sanitize_messages",
]
