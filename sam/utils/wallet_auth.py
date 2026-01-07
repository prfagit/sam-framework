"""Solana wallet authentication utilities.

This module provides functions for verifying Ed25519 signatures from
Solana wallets (Phantom, Solflare, etc.) for authentication purposes.
"""

from __future__ import annotations

import base58
import logging
import secrets
from datetime import datetime, timezone

from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

logger = logging.getLogger(__name__)

# Challenge message format
SIGN_MESSAGE_TEMPLATE = """Sign in to SAM

Wallet: {short_address}
Nonce: {nonce}
Issued: {timestamp}"""

# Nonce configuration
NONCE_LENGTH = 32  # bytes
NONCE_TTL_SECONDS = 300  # 5 minutes


def generate_nonce() -> str:
    """Generate a cryptographically secure random nonce."""
    return secrets.token_urlsafe(NONCE_LENGTH)


def create_sign_message(wallet_address: str, nonce: str) -> str:
    """Create the message that users sign in their wallet.

    Args:
        wallet_address: Full Solana wallet address (base58)
        nonce: Unique challenge nonce

    Returns:
        Message string for the wallet to sign
    """
    short_address = f"{wallet_address[:4]}...{wallet_address[-4:]}"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    return SIGN_MESSAGE_TEMPLATE.format(
        short_address=short_address,
        nonce=nonce,
        timestamp=timestamp,
    )


def verify_solana_signature(
    wallet_address: str,
    signature: str,
    message: str,
) -> bool:
    """Verify an Ed25519 signature from a Solana wallet.

    This verifies that the signature was produced by the private key
    corresponding to the given wallet address (public key).

    Args:
        wallet_address: Solana wallet address (base58-encoded public key)
        signature: Base58-encoded signature from the wallet
        message: The original message that was signed

    Returns:
        True if signature is valid, False otherwise
    """
    try:
        # Decode base58 wallet address to get public key bytes
        pubkey_bytes = base58.b58decode(wallet_address)

        # Validate public key length (Ed25519 = 32 bytes)
        if len(pubkey_bytes) != 32:
            logger.warning(f"Invalid public key length: {len(pubkey_bytes)} bytes")
            return False

        # Decode base58 signature
        signature_bytes = base58.b58decode(signature)

        # Validate signature length (Ed25519 = 64 bytes)
        if len(signature_bytes) != 64:
            logger.warning(f"Invalid signature length: {len(signature_bytes)} bytes")
            return False

        # Encode message as bytes
        message_bytes = message.encode("utf-8")

        # Verify the signature
        verify_key = VerifyKey(pubkey_bytes)
        verify_key.verify(message_bytes, signature_bytes)

        logger.info(f"Signature verified for wallet {wallet_address[:8]}...")
        return True

    except BadSignatureError:
        logger.warning(f"Invalid signature for wallet {wallet_address[:8]}...")
        return False
    except ValueError as e:
        logger.warning(f"Base58 decode error: {e}")
        return False
    except Exception as e:
        logger.error(f"Signature verification error: {e}")
        return False


def validate_wallet_address(wallet_address: str) -> bool:
    """Validate a Solana wallet address format.

    Args:
        wallet_address: Address to validate

    Returns:
        True if valid Solana address format
    """
    try:
        # Check length (typical Solana addresses are 32-44 chars base58)
        if not (32 <= len(wallet_address) <= 44):
            return False

        # Try to decode as base58
        decoded = base58.b58decode(wallet_address)

        # Should be 32 bytes (Ed25519 public key)
        return len(decoded) == 32

    except Exception:
        return False


def derive_user_id(wallet_address: str) -> str:
    """Derive a user ID from a wallet address.

    Creates a short, URL-safe identifier from the wallet address.

    Args:
        wallet_address: Full Solana wallet address

    Returns:
        Short user ID string (e.g., "ABC1xyz9")
    """
    # Use first 4 + last 4 characters of wallet address
    return f"{wallet_address[:4]}{wallet_address[-4:]}".lower()


__all__ = [
    "generate_nonce",
    "create_sign_message",
    "verify_solana_signature",
    "validate_wallet_address",
    "derive_user_id",
    "NONCE_TTL_SECONDS",
]
