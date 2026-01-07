"""Pydantic schemas used by the SAM API."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..agents.definition import AgentDefinition


class AgentSource(str, Enum):
    BUILTIN = "builtin"
    USER = "user"


class AgentVisibility(str, Enum):
    PRIVATE = "private"
    UNLISTED = "unlisted"
    PUBLIC = "public"


class AgentListItem(BaseModel):
    name: str
    description: str = ""
    tags: List[str] = Field(default_factory=list)
    source: AgentSource
    updated_at: Optional[str] = None
    # Sharing status (only populated for USER agents)
    visibility: AgentVisibility = AgentVisibility.PRIVATE
    public_id: Optional[str] = None


class AgentCreateResponse(BaseModel):
    name: str
    source: AgentSource = AgentSource.USER
    path: Optional[str] = None


class AgentDetailResponse(BaseModel):
    source: AgentSource
    definition: AgentDefinition


# =============================================================================
# Wallet Authentication Schemas
# =============================================================================


class ChallengeRequest(BaseModel):
    """Request for a wallet authentication challenge."""

    wallet_address: str = Field(
        ...,
        min_length=32,
        max_length=44,
        description="Solana wallet address (base58 encoded)",
    )


class ChallengeResponse(BaseModel):
    """Response containing the challenge message to sign."""

    message: str = Field(..., description="Message to sign with wallet")
    nonce: str = Field(..., description="Unique nonce for this challenge")
    expires_at: str = Field(..., description="ISO timestamp when challenge expires")


class VerifyRequest(BaseModel):
    """Request to verify a wallet signature."""

    wallet_address: str = Field(
        ...,
        min_length=32,
        max_length=44,
        description="Solana wallet address",
    )
    signature: str = Field(
        ...,
        min_length=64,
        description="Base58-encoded signature from wallet",
    )
    nonce: str = Field(..., description="The nonce from the challenge")


class TokenResponse(BaseModel):
    """JWT token response after successful authentication."""

    access_token: str
    token_type: str = "bearer"
    expires_at: Optional[str] = None
    refresh_token: Optional[str] = None
    refresh_expires_at: Optional[str] = None


# Legacy schemas (kept for backwards compatibility during migration)
class LoginRequest(BaseModel):
    """Legacy username/password login - deprecated."""

    username: str
    password: str


class RegisterRequest(BaseModel):
    """Legacy registration - deprecated."""

    username: str
    password: str


class RegisterResponse(BaseModel):
    """Legacy registration response - deprecated."""

    username: str
    user_id: str
    token: TokenResponse


class RunRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="User prompt to send to the agent")
    session_id: Optional[str] = Field(
        default=None,
        description="Existing session identifier. When omitted a new session is created.",
    )


class RunResponse(BaseModel):
    session_id: str
    response: str
    usage: Dict[str, int] = Field(default_factory=dict)
    events: List[Dict[str, Any]] = Field(default_factory=list)


class SessionListItem(BaseModel):
    session_id: str
    agent_name: Optional[str] = None
    session_name: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    message_count: int = 0
    last_message: Optional[str] = None


class SessionDetailResponse(BaseModel):
    session_id: str
    agent_name: Optional[str] = None
    session_name: Optional[str] = None
    messages: List[Dict[str, Any]] = Field(default_factory=list)


class SessionCreateRequest(BaseModel):
    session_id: Optional[str] = None
    agent_name: Optional[str] = None
    session_name: Optional[str] = None
    messages: Optional[List[Dict[str, Any]]] = None


class SessionUpdateRequest(BaseModel):
    session_name: Optional[str] = None


class SessionCreateResponse(BaseModel):
    session_id: str


class RefreshTokenRequest(BaseModel):
    refresh_token: Optional[str] = None  # Optional since cookie is preferred


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


# =============================================================================
# Onboarding Schemas
# =============================================================================


class OnboardingStatusResponse(BaseModel):
    """User's onboarding status."""

    onboarding_complete: bool
    username: Optional[str] = None
    has_operational_wallet: bool = False


class CheckUsernameRequest(BaseModel):
    """Request to check username availability."""

    username: str = Field(
        ...,
        min_length=3,
        max_length=30,
        pattern=r"^[a-zA-Z0-9_]+$",
        description="Username (3-30 chars, alphanumeric + underscore only)",
    )


class CheckUsernameResponse(BaseModel):
    """Response for username availability check."""

    available: bool
    username: str


class CompleteOnboardingRequest(BaseModel):
    """Request to complete onboarding."""

    username: str = Field(
        ...,
        min_length=3,
        max_length=30,
        pattern=r"^[a-zA-Z0-9_]+$",
        description="Chosen username",
    )


class OperationalWalletInfo(BaseModel):
    """Operational wallet information (private key shown ONCE)."""

    public_key: str = Field(..., description="Public wallet address")
    private_key: str = Field(
        ...,
        description="Private key shown ONCE during onboarding for backup. Never returned again.",
    )


class CompleteOnboardingResponse(BaseModel):
    """Response after completing onboarding with generated wallet."""

    success: bool
    username: str
    operational_wallet: OperationalWalletInfo


class UserProfileResponse(BaseModel):
    """Full user profile including onboarding status."""

    user_id: str
    wallet_address: str = Field(..., description="Login wallet (Phantom/Solflare)")
    username: Optional[str] = None
    is_admin: bool = False
    onboarding_complete: bool = False
    operational_wallet_address: Optional[str] = Field(
        default=None, description="Operational wallet public address (for trading)"
    )
    created_at: str


class QuotaUsage(BaseModel):
    used: int
    limit: int
    remaining: int


class TokenQuotaUsage(BaseModel):
    used_today: int
    limit: int
    remaining: int
    resets_at: Optional[str] = None


class QuotaStatusResponse(BaseModel):
    user_id: str
    sessions: QuotaUsage
    agents: QuotaUsage
    tokens: TokenQuotaUsage
    messages_per_session: Dict[str, int] = Field(default_factory=dict)


# =============================================================================
# Public Agent / Marketplace Schemas
# =============================================================================


class PublicAgentListItem(BaseModel):
    """Public agent item for marketplace listing."""

    public_id: str
    agent_name: str
    description: str = ""
    author: Optional[str] = None
    author_id: str
    tags: List[str] = Field(default_factory=list)
    visibility: AgentVisibility
    download_count: int = 0
    rating: Optional[float] = None
    rating_count: int = 0
    published_at: Optional[str] = None


class PublicAgentDetailResponse(BaseModel):
    """Full public agent details including definition."""

    public_id: str
    visibility: AgentVisibility
    share_token: Optional[str] = None
    download_count: int = 0
    rating: Optional[float] = None
    rating_count: int = 0
    published_at: Optional[str] = None
    definition: AgentDefinition
    author_id: str
    author_name: Optional[str] = None
    user_rating: Optional[int] = None  # Current user's rating if any


class PublishAgentRequest(BaseModel):
    """Request to publish an agent."""

    visibility: AgentVisibility = AgentVisibility.PUBLIC


class PublishAgentResponse(BaseModel):
    """Response after publishing an agent."""

    public_id: str
    visibility: AgentVisibility
    share_token: Optional[str] = None
    published_at: Optional[str] = None


class ShareAgentResponse(BaseModel):
    """Response with share link information."""

    public_id: str
    share_token: str
    share_url: str


class CloneAgentRequest(BaseModel):
    """Request to clone a public agent."""

    new_name: Optional[str] = Field(
        default=None,
        description="Custom name for cloned agent. If not provided, original name with suffix is used.",
    )


class CloneAgentResponse(BaseModel):
    """Response after cloning an agent."""

    name: str
    source: AgentSource = AgentSource.USER
    cloned_from: str  # Original public_id


class RateAgentRequest(BaseModel):
    """Request to rate an agent."""

    rating: int = Field(..., ge=1, le=5, description="Rating from 1 to 5 stars")
    comment: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional comment with the rating",
    )


class AgentRatingResponse(BaseModel):
    """Single rating response."""

    user_id: str
    rating: int
    comment: Optional[str] = None
    created_at: str


class AgentRatingsListResponse(BaseModel):
    """List of ratings for an agent."""

    public_id: str
    average_rating: Optional[float] = None
    rating_count: int = 0
    ratings: List[AgentRatingResponse] = Field(default_factory=list)
    total: int = 0


class PublicAgentsListResponse(BaseModel):
    """Paginated list of public agents."""

    agents: List[PublicAgentListItem] = Field(default_factory=list)
    total: int = 0
    limit: int = 20
    offset: int = 0


__all__ = [
    # Agent schemas
    "AgentCreateResponse",
    "AgentDetailResponse",
    "AgentListItem",
    "AgentSource",
    "AgentVisibility",
    # Wallet auth schemas
    "ChallengeRequest",
    "ChallengeResponse",
    "VerifyRequest",
    "TokenResponse",
    "RefreshTokenRequest",
    "LogoutRequest",
    # Legacy auth schemas (deprecated)
    "LoginRequest",
    "RegisterRequest",
    "RegisterResponse",
    # Onboarding schemas
    "OnboardingStatusResponse",
    "CheckUsernameRequest",
    "CheckUsernameResponse",
    "CompleteOnboardingRequest",
    "CompleteOnboardingResponse",
    "OperationalWalletInfo",
    "UserProfileResponse",
    # Run schemas
    "RunRequest",
    "RunResponse",
    # Session schemas
    "SessionCreateRequest",
    "SessionCreateResponse",
    "SessionDetailResponse",
    "SessionListItem",
    "SessionUpdateRequest",
    # Quota schemas
    "QuotaStatusResponse",
    "QuotaUsage",
    "TokenQuotaUsage",
    # Public agent / marketplace schemas
    "PublicAgentListItem",
    "PublicAgentDetailResponse",
    "PublicAgentsListResponse",
    "PublishAgentRequest",
    "PublishAgentResponse",
    "ShareAgentResponse",
    "CloneAgentRequest",
    "CloneAgentResponse",
    "RateAgentRequest",
    "AgentRatingResponse",
    "AgentRatingsListResponse",
]
