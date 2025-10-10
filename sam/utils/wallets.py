"""Wallet helpers for Solana and EVM chains."""

from __future__ import annotations

import base58
import json
from typing import Tuple

from eth_account import Account
from solders.keypair import Keypair


class WalletError(Exception):
    """Generic wallet helper error."""


def generate_solana_wallet() -> Tuple[str, str]:
    """Generate a Solana wallet returning (private_key_base58, public_address)."""

    keypair = Keypair()
    private_key_b58 = base58.b58encode(bytes(keypair)).decode()
    return private_key_b58, str(keypair.pubkey())


def decode_solana_private_key(private_key: str) -> bytes:
    """Decode a Solana private key from base58 or JSON array formats."""

    if not private_key:
        raise WalletError("Solana private key cannot be empty")

    # Try base58
    try:
        decoded = base58.b58decode(private_key)
        if len(decoded) in (64, 32):
            return decoded
    except Exception:
        pass

    # Try JSON array
    try:
        arr = json.loads(private_key)
        if isinstance(arr, list) and all(isinstance(i, int) for i in arr) and len(arr) in (64, 32):
            return bytes(arr)
    except Exception:
        pass

    raise WalletError(
        "Unsupported Solana private key format. Provide base58 string or JSON array of bytes."
    )


def derive_solana_address(private_key: str) -> str:
    """Derive Solana public address from a private key string."""

    private_key_bytes = decode_solana_private_key(private_key)
    keypair = Keypair.from_bytes(private_key_bytes)
    return str(keypair.pubkey())


def generate_evm_wallet() -> Tuple[str, str]:
    """Generate an EVM wallet returning (private_key_hex, address)."""

    account = Account.create()
    return account.key.hex(), account.address


def normalize_evm_private_key(private_key: str) -> str:
    """Normalize an EVM private key to 0x-prefixed hex."""

    if not private_key:
        raise WalletError("EVM private key cannot be empty")

    key = private_key.strip()
    if not key.startswith("0x"):
        key = "0x" + key
    if len(key) != 66:
        raise WalletError("EVM private key must be 32 bytes (64 hex characters)")
    return key


def derive_evm_address(private_key: str) -> str:
    """Derive an EVM address from private key string."""

    normalized_key = normalize_evm_private_key(private_key)
    try:
        account = Account.from_key(normalized_key)
    except Exception as exc:  # pragma: no cover - defensive guard
        raise WalletError(f"Invalid EVM private key: {exc}") from exc
    # Account.address is typed as Any in eth-account, but it's always a str
    address: str = str(account.address)
    return address
