"""Authentication utilities for the SAM API.

This module provides wallet-based authentication using Solana wallets
(Phantom, Solflare, etc.) with Ed25519 signature verification.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt

from ..config.settings import Settings
from ..utils.connection_pool import get_db_connection
from ..core.migration_definitions import register_all_migrations
from ..core.migrations import get_migration_manager
from ..utils.wallet_auth import (
    create_sign_message,
    derive_user_id,
    generate_nonce,
    validate_wallet_address,
    verify_solana_signature,
    NONCE_TTL_SECONDS,
)

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"


@dataclass(slots=True)
class User:
    """User authenticated via Solana wallet."""

    wallet_address: str
    user_id: str
    display_name: Optional[str]
    is_admin: bool
    created_at: str


@dataclass(slots=True)
class WalletChallenge:
    """Challenge nonce for wallet authentication."""

    wallet_address: str
    nonce: str
    message: str
    created_at: str
    expires_at: str


class UserStore:
    """Database-backed user store for wallet authentication."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def initialize(self) -> None:
        """Initialize database tables and run migrations."""
        # Register and run migrations
        await register_all_migrations(self.db_path)
        manager = get_migration_manager(self.db_path)
        await manager.initialize()
        applied = await manager.migrate()
        if applied > 0:
            logger.info(f"Applied {applied} migration(s) for auth database")

        # Ensure tables exist (backward compatibility)
        async with get_db_connection(self.db_path) as conn:
            # Users table with wallet support
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS api_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE,
                    user_id TEXT NOT NULL UNIQUE,
                    password_hash TEXT,
                    wallet_address TEXT UNIQUE,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_api_users_wallet ON api_users(wallet_address)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_api_users_user_id ON api_users(user_id)"
            )

            # Refresh tokens table
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS refresh_tokens (
                    token_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id, expires_at)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_hash ON refresh_tokens(token_hash)"
            )

            # Wallet challenges table
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS wallet_challenges (
                    wallet_address TEXT PRIMARY KEY,
                    nonce TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_wallet_challenges_expires ON wallet_challenges(expires_at)"
            )

            await conn.commit()

    # =========================================================================
    # Wallet User Methods
    # =========================================================================

    async def get_user_by_wallet(self, wallet_address: str) -> Optional[User]:
        """Get user by wallet address."""
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT wallet_address, user_id, username, is_admin, created_at
                FROM api_users
                WHERE wallet_address = ?
                """,
                (wallet_address,),
            )
            row = await cursor.fetchone()

        if not row:
            return None

        return User(
            wallet_address=row[0],
            user_id=row[1],
            display_name=row[2],  # username serves as display name
            is_admin=bool(row[3]),
            created_at=row[4],
        )

    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get user by user_id (for refresh token verification)."""
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT wallet_address, user_id, username, is_admin, created_at
                FROM api_users
                WHERE user_id = ?
                """,
                (user_id,),
            )
            row = await cursor.fetchone()

        if not row:
            return None

        return User(
            wallet_address=row[0],
            user_id=row[1],
            display_name=row[2],
            is_admin=bool(row[3]),
            created_at=row[4],
        )

    async def create_wallet_user(self, wallet_address: str, *, is_admin: bool = False) -> User:
        """Create a new user from wallet address."""
        if not validate_wallet_address(wallet_address):
            raise ValueError("Invalid wallet address format")

        # Check if user already exists
        existing = await self.get_user_by_wallet(wallet_address)
        if existing:
            raise ValueError("Wallet already registered")

        user_id = derive_user_id(wallet_address)
        created_at = datetime.now(timezone.utc).isoformat()
        # Use wallet address as username (for legacy schema compatibility)
        # Password hash is empty - wallet users authenticate via signature
        username = f"wallet_{wallet_address[:8].lower()}"
        password_hash = ""  # No password for wallet users

        async with get_db_connection(self.db_path) as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO api_users (username, user_id, password_hash, wallet_address, is_admin, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (username, user_id, password_hash, wallet_address, int(is_admin), created_at),
                )
                await conn.commit()
            except Exception as exc:
                logger.error(f"Failed to create wallet user: {exc}")
                if "UNIQUE constraint" in str(exc):
                    raise ValueError("Wallet already registered") from exc
                raise

        logger.info(f"Created wallet user: {wallet_address[:8]}... -> {user_id}")
        return User(
            wallet_address=wallet_address,
            user_id=user_id,
            display_name=None,
            is_admin=is_admin,
            created_at=created_at,
        )

    async def get_or_create_wallet_user(self, wallet_address: str) -> User:
        """Get existing user or create new one from wallet address."""
        user = await self.get_user_by_wallet(wallet_address)
        if user:
            return user
        return await self.create_wallet_user(wallet_address)

    # =========================================================================
    # Challenge/Nonce Methods
    # =========================================================================

    async def store_challenge(
        self, wallet_address: str, nonce: str, message: str
    ) -> WalletChallenge:
        """Store a challenge nonce for wallet authentication."""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=NONCE_TTL_SECONDS)

        async with get_db_connection(self.db_path) as conn:
            # Upsert - replace any existing challenge for this wallet
            await conn.execute(
                """
                INSERT INTO wallet_challenges (wallet_address, nonce, message, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(wallet_address) DO UPDATE SET
                    nonce = excluded.nonce,
                    message = excluded.message,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at
                """,
                (
                    wallet_address,
                    nonce,
                    message,
                    now.isoformat(),
                    expires_at.isoformat(),
                ),
            )
            await conn.commit()

        return WalletChallenge(
            wallet_address=wallet_address,
            nonce=nonce,
            message=message,
            created_at=now.isoformat(),
            expires_at=expires_at.isoformat(),
        )

    async def get_challenge(self, wallet_address: str) -> Optional[WalletChallenge]:
        """Get the active challenge for a wallet address."""
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT wallet_address, nonce, message, created_at, expires_at
                FROM wallet_challenges
                WHERE wallet_address = ?
                """,
                (wallet_address,),
            )
            row = await cursor.fetchone()

        if not row:
            return None

        # Check if expired
        expires_at = datetime.fromisoformat(row[4].replace("Z", "+00:00"))
        if expires_at < datetime.now(timezone.utc):
            # Expired - delete and return None
            await self.delete_challenge(wallet_address)
            return None

        return WalletChallenge(
            wallet_address=row[0],
            nonce=row[1],
            message=row[2],
            created_at=row[3],
            expires_at=row[4],
        )

    async def delete_challenge(self, wallet_address: str) -> bool:
        """Delete a challenge after use or expiration."""
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                "DELETE FROM wallet_challenges WHERE wallet_address = ?",
                (wallet_address,),
            )
            await conn.commit()
        return cursor.rowcount > 0

    async def cleanup_expired_challenges(self) -> int:
        """Remove all expired challenges. Returns count of deleted rows."""
        now = datetime.now(timezone.utc).isoformat()
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                "DELETE FROM wallet_challenges WHERE expires_at < ?",
                (now,),
            )
            await conn.commit()
        count = cursor.rowcount or 0
        if count > 0:
            logger.debug(f"Cleaned up {count} expired wallet challenges")
        return count


# =============================================================================
# JWT Token Functions
# =============================================================================


def _secret_key() -> str:
    """Get the JWT secret key from settings."""
    Settings.refresh_from_env()
    secret = Settings.SAM_API_TOKEN_SECRET or Settings.SAM_FERNET_KEY
    if not secret:
        raise RuntimeError(
            "API token secret not configured. Set SAM_API_TOKEN_SECRET or SAM_FERNET_KEY."
        )
    return secret


def create_access_token(*, wallet_address: str, user_id: str) -> tuple[str, datetime]:
    """Create a short-lived access token (default: 15 minutes)."""
    expire_minutes = max(1, int(Settings.SAM_API_TOKEN_EXPIRE_MINUTES or 15))
    expire = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
    payload = {
        "sub": wallet_address,  # Subject is wallet address
        "uid": user_id,
        "exp": expire,
        "type": "access",
    }
    token = jwt.encode(payload, _secret_key(), algorithm=JWT_ALGORITHM)
    return token, expire


async def create_refresh_token(*, wallet_address: str, user_id: str) -> tuple[str, datetime]:
    """Create a long-lived refresh token (default: 7 days) and store it in database."""
    import base64
    import hashlib
    import secrets

    expire_days = max(1, int(Settings.SAM_API_REFRESH_TOKEN_EXPIRE_DAYS or 7))
    expire = datetime.now(timezone.utc) + timedelta(days=expire_days)

    # Generate a secure random token
    token_bytes = secrets.token_bytes(32)
    token_str = base64.urlsafe_b64encode(token_bytes).decode("utf-8").rstrip("=")

    # Hash the token for storage (never store plaintext)
    token_hash = hashlib.sha256(token_str.encode()).hexdigest()

    # Store in database
    token_id = secrets.token_urlsafe(16)
    created_at = datetime.now(timezone.utc).isoformat()
    expires_at = expire.isoformat()

    async with get_db_connection(Settings.SAM_DB_PATH) as conn:
        await conn.execute(
            """
            INSERT INTO refresh_tokens (token_id, user_id, token_hash, expires_at, created_at, revoked)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (token_id, user_id, token_hash, expires_at, created_at),
        )
        await conn.commit()

    logger.debug(f"Created refresh token for user {user_id}")
    return token_str, expire


async def verify_refresh_token(token: str) -> Optional[User]:
    """Verify a refresh token and return the associated user."""
    import hashlib

    # Hash the provided token
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    async with get_db_connection(Settings.SAM_DB_PATH) as conn:
        cursor = await conn.execute(
            """
            SELECT user_id, expires_at, revoked
            FROM refresh_tokens
            WHERE token_hash = ?
            """,
            (token_hash,),
        )
        row = await cursor.fetchone()

    if not row:
        logger.debug("Refresh token not found")
        return None

    user_id, expires_at_str, revoked = row

    # Check if revoked
    if revoked:
        logger.debug("Refresh token has been revoked")
        return None

    # Check if expired
    try:
        expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        if expires_at < datetime.now(timezone.utc):
            logger.debug("Refresh token has expired")
            return None
    except Exception:
        logger.warning("Invalid refresh token expiration date")
        return None

    # Get user from user_id
    store = await get_user_store()
    user = await store.get_user_by_id(user_id)
    if not user:
        logger.debug(f"User not found for user_id: {user_id}")
        return None

    return user


async def revoke_refresh_token(token: str) -> bool:
    """Revoke a refresh token."""
    import hashlib

    token_hash = hashlib.sha256(token.encode()).hexdigest()

    async with get_db_connection(Settings.SAM_DB_PATH) as conn:
        cursor = await conn.execute(
            """
            UPDATE refresh_tokens
            SET revoked = 1
            WHERE token_hash = ?
            """,
            (token_hash,),
        )
        await conn.commit()

    return cursor.rowcount > 0


async def revoke_all_user_refresh_tokens(user_id: str) -> int:
    """Revoke all refresh tokens for a user."""
    async with get_db_connection(Settings.SAM_DB_PATH) as conn:
        cursor = await conn.execute(
            """
            UPDATE refresh_tokens
            SET revoked = 1
            WHERE user_id = ? AND revoked = 0
            """,
            (user_id,),
        )
        await conn.commit()

    return cursor.rowcount or 0


async def decode_access_token(token: str) -> User:
    """Decode and validate an access token, returning the user."""
    try:
        payload = jwt.decode(token, _secret_key(), algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid token") from exc

    wallet_address = payload.get("sub")
    if not isinstance(wallet_address, str):
        raise ValueError("Token missing subject")

    store = await get_user_store()
    user = await store.get_user_by_wallet(wallet_address)
    if not user:
        # Try by user_id for backward compatibility
        user_id = payload.get("uid")
        if user_id:
            user = await store.get_user_by_id(user_id)
    if not user:
        raise ValueError("User not found")
    return user


# =============================================================================
# Wallet Authentication Flow
# =============================================================================


async def create_wallet_challenge(wallet_address: str) -> WalletChallenge:
    """Create a new challenge for wallet authentication.

    Args:
        wallet_address: The Solana wallet address requesting authentication

    Returns:
        WalletChallenge with nonce and message to sign

    Raises:
        ValueError: If wallet address is invalid
    """
    if not validate_wallet_address(wallet_address):
        raise ValueError("Invalid wallet address format")

    store = await get_user_store()

    # Generate nonce and message
    nonce = generate_nonce()
    message = create_sign_message(wallet_address, nonce)

    # Store challenge
    challenge = await store.store_challenge(wallet_address, nonce, message)
    logger.debug(f"Created challenge for wallet {wallet_address[:8]}...")

    return challenge


async def verify_wallet_challenge(
    wallet_address: str, signature: str, nonce: str
) -> Optional[User]:
    """Verify a wallet signature and authenticate the user.

    Args:
        wallet_address: The Solana wallet address
        signature: Base58-encoded signature from wallet
        nonce: The nonce that was signed

    Returns:
        Authenticated User if successful, None otherwise
    """
    store = await get_user_store()
    logger.info(f"Verifying wallet challenge for {wallet_address[:8]}...")

    # Get the stored challenge
    challenge = await store.get_challenge(wallet_address)
    if not challenge:
        logger.warning(f"No challenge found for wallet {wallet_address[:8]}...")
        return None

    logger.info(f"Found challenge, nonce={challenge.nonce[:8]}...")

    # Verify nonce matches
    if challenge.nonce != nonce:
        logger.warning(
            f"Nonce mismatch for wallet {wallet_address[:8]}... expected={challenge.nonce[:8]}, got={nonce[:8]}"
        )
        return None

    logger.info("Nonce matched, verifying signature...")
    logger.debug(f"Message to verify: {challenge.message}")
    logger.debug(f"Signature (first 20 chars): {signature[:20]}...")

    # Verify signature
    if not verify_solana_signature(wallet_address, signature, challenge.message):
        logger.warning(f"Invalid signature for wallet {wallet_address[:8]}...")
        return None

    logger.info("Signature verified successfully!")

    # Delete the used challenge (single-use)
    await store.delete_challenge(wallet_address)

    # Get or create user
    user = await store.get_or_create_wallet_user(wallet_address)
    logger.info(f"Wallet authenticated: {wallet_address[:8]}... -> {user.user_id}")

    return user


# =============================================================================
# Global User Store Singleton
# =============================================================================

_USER_STORE: Optional[UserStore] = None
_USER_LOCK = asyncio.Lock()


async def get_user_store() -> UserStore:
    """Get the global UserStore instance."""
    global _USER_STORE
    db_path = Settings.SAM_DB_PATH
    if _USER_STORE is not None and _USER_STORE.db_path == db_path:
        return _USER_STORE
    async with _USER_LOCK:
        if _USER_STORE is None or _USER_STORE.db_path != db_path:
            logger.debug("Initializing user store for database: %s", db_path)
            _USER_STORE = UserStore(db_path)
            await _USER_STORE.initialize()
            logger.debug("User store initialized")
    return _USER_STORE


__all__ = [
    "User",
    "UserStore",
    "WalletChallenge",
    "create_access_token",
    "create_refresh_token",
    "create_wallet_challenge",
    "decode_access_token",
    "get_user_store",
    "revoke_all_user_refresh_tokens",
    "revoke_refresh_token",
    "verify_refresh_token",
    "verify_wallet_challenge",
]
