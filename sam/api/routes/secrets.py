"""User secrets management API.

Users can store their own API keys for integrations like Polymarket, Hyperliquid, etc.
These are stored encrypted per-user and never exposed to other users.
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..dependencies import APIUser, get_current_user
from ..user_secrets import UserSecretsStore
from ..services.onboarding import OnboardingService
from ...config.settings import Settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/secrets", tags=["secrets"])

# Define available integrations that users can configure
AVAILABLE_INTEGRATIONS = {
    "solana": {
        "name": "Solana Wallet",
        "description": "Solana wallet for transactions",
        "fields": ["private_key"],
    },
    "polymarket": {
        "name": "Polymarket",
        "description": "Prediction market trading",
        "fields": ["api_key", "api_secret"],
    },
    "hyperliquid": {
        "name": "Hyperliquid",
        "description": "Perpetuals DEX trading",
        "fields": ["api_key", "api_secret"],
    },
    "coinbase": {
        "name": "Coinbase",
        "description": "Coinbase exchange integration",
        "fields": ["api_key", "api_secret"],
    },
    "kalshi": {
        "name": "Kalshi",
        "description": "Event contracts trading",
        "fields": ["api_key"],
    },
    "brave": {
        "name": "Brave Search",
        "description": "Web search API",
        "fields": ["api_key"],
    },
}


class IntegrationInfo(BaseModel):
    """Info about an available integration."""

    id: str
    name: str
    description: str
    fields: List[str]
    configured: bool = False


class SetSecretRequest(BaseModel):
    """Request to set a secret value."""

    integration: str = Field(..., description="Integration ID")
    field: str = Field(..., description="Field name (api_key, api_secret, etc)")
    value: str = Field(..., description="Secret value")


class DeleteSecretRequest(BaseModel):
    """Request to delete a secret."""

    integration: str
    field: str


class SecretStatus(BaseModel):
    """Status of a secret (without revealing the value)."""

    integration: str
    field: str
    is_set: bool


@router.get("/integrations", response_model=List[IntegrationInfo])
async def list_integrations(
    user: APIUser = Depends(get_current_user),
) -> List[IntegrationInfo]:
    """List available integrations and their configuration status."""
    store = UserSecretsStore()
    configured = set(await store.get_configured_integrations(user.user_id))

    # Also check for operational wallet (counts as Solana being configured)
    onboarding = OnboardingService(Settings.SAM_DB_PATH)
    has_operational_wallet = await onboarding.get_operational_wallet_address(user.user_id)
    if has_operational_wallet:
        configured.add("solana")

    result = []
    for int_id, info in AVAILABLE_INTEGRATIONS.items():
        result.append(
            IntegrationInfo(
                id=int_id,
                name=info["name"],
                description=info["description"],
                fields=info["fields"],
                configured=int_id in configured,
            )
        )
    return result


@router.get("/status", response_model=List[SecretStatus])
async def get_secrets_status(
    user: APIUser = Depends(get_current_user),
) -> List[SecretStatus]:
    """Get status of all user secrets (which ones are set)."""
    store = UserSecretsStore()
    statuses = await store.get_all_statuses(user.user_id)
    result = [
        SecretStatus(integration=s["integration"], field=s["field"], is_set=s["is_set"])
        for s in statuses
    ]

    # Also check for operational wallet (counts as Solana private_key being set)
    onboarding = OnboardingService(Settings.SAM_DB_PATH)
    has_operational_wallet = await onboarding.get_operational_wallet_address(user.user_id)
    if has_operational_wallet:
        # Check if solana.private_key is already in the list
        solana_key_exists = any(
            s.integration == "solana" and s.field == "private_key" for s in result
        )
        if not solana_key_exists:
            result.append(SecretStatus(integration="solana", field="private_key", is_set=True))

    return result


@router.post("/set")
async def set_secret(
    request: SetSecretRequest,
    user: APIUser = Depends(get_current_user),
) -> dict:
    """Set a secret value for an integration."""
    # Validate integration
    if request.integration not in AVAILABLE_INTEGRATIONS:
        raise HTTPException(status_code=400, detail="Unknown integration")

    # Validate field
    valid_fields = AVAILABLE_INTEGRATIONS[request.integration]["fields"]
    if request.field not in valid_fields:
        raise HTTPException(status_code=400, detail="Invalid field for this integration")

    store = UserSecretsStore()
    success = await store.set_secret(
        user_id=user.user_id,
        integration=request.integration,
        field=request.field,
        value=request.value,
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to store secret")

    logger.info(f"User {user.user_id} set secret for {request.integration}.{request.field}")
    return {"success": True}


@router.post("/delete")
async def delete_secret(
    request: DeleteSecretRequest,
    user: APIUser = Depends(get_current_user),
) -> dict:
    """Delete a secret value."""
    store = UserSecretsStore()
    success = await store.delete_secret(
        user_id=user.user_id,
        integration=request.integration,
        field=request.field,
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete secret")

    logger.info(f"User {user.user_id} deleted secret for {request.integration}.{request.field}")
    return {"success": True}


@router.delete("/integration/{integration_id}")
async def delete_integration_secrets(
    integration_id: str,
    user: APIUser = Depends(get_current_user),
) -> dict:
    """Delete all secrets for an integration."""
    if integration_id not in AVAILABLE_INTEGRATIONS:
        raise HTTPException(status_code=400, detail="Unknown integration")

    store = UserSecretsStore()
    success = await store.delete_integration(user.user_id, integration_id)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete integration secrets")

    logger.info(f"User {user.user_id} deleted all secrets for {integration_id}")
    return {"success": True}
