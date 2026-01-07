"""Onboarding service for managing user setup."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from ...utils.connection_pool import get_db_connection
from ...utils.crypto import decrypt_private_key, encrypt_private_key
from ...utils.wallets import generate_solana_wallet
from ..dependencies import APIUser
from ..schemas import (
    CompleteOnboardingResponse,
    OnboardingStatusResponse,
    OperationalWalletInfo,
    UserProfileResponse,
)
from ..user_secrets import UserSecretsStore

logger = logging.getLogger(__name__)


class OnboardingService:
    """Service for managing user onboarding process."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def get_status(self, user_id: str) -> OnboardingStatusResponse:
        """Get user's current onboarding status."""
        async with get_db_connection(self.db_path) as conn:
            # Get user onboarding status
            cursor = await conn.execute(
                """
                SELECT onboarding_complete, display_username
                FROM api_users WHERE user_id = ?
                """,
                (user_id,),
            )
            user_row = await cursor.fetchone()

            # Check for operational wallet
            cursor = await conn.execute(
                "SELECT 1 FROM operational_wallets WHERE user_id = ?",
                (user_id,),
            )
            has_wallet = await cursor.fetchone() is not None

        if not user_row:
            return OnboardingStatusResponse(
                onboarding_complete=False,
                username=None,
                has_operational_wallet=False,
            )

        return OnboardingStatusResponse(
            onboarding_complete=bool(user_row[0]),
            username=user_row[1],
            has_operational_wallet=has_wallet,
        )

    async def is_username_available(self, username: str) -> bool:
        """Check if username is available (case-insensitive)."""
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                "SELECT 1 FROM api_users WHERE LOWER(display_username) = LOWER(?)",
                (username,),
            )
            return await cursor.fetchone() is None

    async def complete_onboarding(
        self,
        user_id: str,
        username: str,
    ) -> CompleteOnboardingResponse:
        """Complete onboarding: set username, generate and store encrypted wallet.

        Returns the generated wallet info including private key (shown ONCE).
        """
        # Generate operational wallet
        private_key, public_address = generate_solana_wallet()

        # Encrypt the private key for storage
        encrypted_key = encrypt_private_key(private_key)

        now = datetime.now(timezone.utc).isoformat()

        async with get_db_connection(self.db_path) as conn:
            # Update user with username and mark onboarding complete
            await conn.execute(
                """
                UPDATE api_users
                SET display_username = ?, onboarding_complete = 1
                WHERE user_id = ?
                """,
                (username, user_id),
            )

            # Store operational wallet
            await conn.execute(
                """
                INSERT INTO operational_wallets
                (user_id, wallet_address, encrypted_private_key, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, public_address, encrypted_key, now),
            )

            await conn.commit()

        # Also store the private key in user_secrets so integrations show as configured
        secrets_store = UserSecretsStore()
        await secrets_store.set_secret(
            user_id=user_id,
            integration="solana",
            field="private_key",
            value=private_key,
        )

        logger.info(
            "Onboarding completed for %s...: username=%s, wallet=%s...",
            user_id[:8],
            username,
            public_address[:8],
        )

        return CompleteOnboardingResponse(
            success=True,
            username=username,
            operational_wallet=OperationalWalletInfo(
                public_key=public_address,
                private_key=private_key,  # Shown only once!
            ),
        )

    async def get_operational_wallet_key(self, user_id: str) -> Optional[str]:
        """Get decrypted operational wallet private key for Solana operations.

        This is used internally by the trading/agent system, never exposed via API.
        """
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                "SELECT encrypted_private_key FROM operational_wallets WHERE user_id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()

        if not row:
            return None

        return decrypt_private_key(row[0])

    async def get_operational_wallet_address(self, user_id: str) -> Optional[str]:
        """Get operational wallet public address."""
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                "SELECT wallet_address FROM operational_wallets WHERE user_id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()

        return row[0] if row else None

    async def get_user_profile(self, user_id: str, user: APIUser) -> UserProfileResponse:
        """Get full user profile with onboarding status."""
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT u.display_username, u.onboarding_complete, u.created_at,
                       w.wallet_address as op_wallet
                FROM api_users u
                LEFT JOIN operational_wallets w ON u.user_id = w.user_id
                WHERE u.user_id = ?
                """,
                (user_id,),
            )
            row = await cursor.fetchone()

        if not row:
            # User exists (from auth) but not fully in DB yet
            return UserProfileResponse(
                user_id=user_id,
                wallet_address=user.wallet_address,
                username=None,
                is_admin=user.is_admin,
                onboarding_complete=False,
                operational_wallet_address=None,
                created_at=datetime.now(timezone.utc).isoformat(),
            )

        return UserProfileResponse(
            user_id=user_id,
            wallet_address=user.wallet_address,
            username=row[0],
            is_admin=user.is_admin,
            onboarding_complete=bool(row[1]),
            operational_wallet_address=row[3],
            created_at=row[2],
        )


__all__ = ["OnboardingService"]
