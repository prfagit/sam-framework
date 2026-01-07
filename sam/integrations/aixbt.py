"""AIXBT intelligence and research tools."""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..core.tools import Tool, ToolSpec

try:  # pragma: no cover - optional dependency handled at runtime
    from eth_account import Account  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    Account = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency handled at runtime
    from x402.clients.httpx import x402HttpxClient  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    x402HttpxClient = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class AixbtError(RuntimeError):
    """Raised when the AIXBT API returns an error or malformed response."""


def _extract_error(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    for key in ("error", "message", "detail", "title"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _summarize_project(project: Dict[str, Any]) -> Dict[str, Any]:
    """Produce a condensed, agent-friendly representation of a project record."""
    summary = {
        "name": project.get("name"),
        "ticker": project.get("ticker"),
        "score": project.get("score"),
        "popularity_score": project.get("popularityScore"),
        "momentum_score": project.get("momentumScore"),
        "mentions_24h": project.get("mentions24h")
        or project.get("mentions_24h")
        or project.get("mentionCount"),
        "price": project.get("price"),
        "market_cap": project.get("marketCap"),
        "category": project.get("category"),
        "x_handle": project.get("xHandle"),
        "summary": project.get("rationale") or project.get("summary"),
        "url": project.get("url"),
        "links": project.get("links"),
    }
    # Drop keys with falsy values to keep responses concise
    return {key: value for key, value in summary.items() if value not in (None, "", [], {})}


class ProjectsInput(BaseModel):
    """Filter options for listing projects."""

    limit: int = Field(default=25, ge=1, le=50)
    name: Optional[str] = Field(default=None, description="Regex filter on project name")
    ticker: Optional[str] = Field(default=None, description="Exact ticker symbol filter")
    x_handle: Optional[str] = Field(
        default=None, alias="xHandle", description="Filter by associated X / Twitter handle"
    )
    sort_by: Optional[Literal["score", "popularityScore"]] = Field(
        default=None,
        alias="sortBy",
        description="Sort results by score (default) or popularityScore",
    )
    min_score: Optional[float] = Field(
        default=None,
        alias="minScore",
        ge=0,
        description="Only include projects with a minimum composite score",
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)


class IndigoMessage(BaseModel):
    """Single chat message for the Indigo research agent."""

    role: Literal["system", "user", "assistant"]
    content: str

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class IndigoAgentInput(BaseModel):
    """Input payload for Indigo agent conversations."""

    prompt: Optional[str] = Field(
        default=None,
        description="Convenience field to build a single user message without specifying messages.",
    )
    messages: Optional[List[IndigoMessage]] = Field(
        default=None, description="Full message list for multi-turn conversations."
    )

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def ensure_messages(cls, model: "IndigoAgentInput") -> "IndigoAgentInput":
        if model.prompt and not model.messages:
            model.messages = [IndigoMessage(role="user", content=model.prompt)]
        if not model.messages:
            raise ValueError("Provide either prompt or messages for the Indigo agent.")
        return model


@dataclass
class IndigoResult:
    """Normalized Indigo agent response."""

    result: Dict[str, Any]
    payment: Optional[Dict[str, Any]]


class AixbtClient:
    """Async HTTP client for the AIXBT API using the x402 payment flow."""

    def __init__(
        self,
        *,
        base_url: str = "https://api.aixbt.tech",
        private_key: Optional[str] = None,
        account: Optional[Any] = None,
        request_timeout: Optional[float] = None,
        client_factory: Optional[Callable[[Any, str, Optional[float]], Any]] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        # Default to 60s for Base network settlement if not specified
        self._request_timeout = request_timeout if request_timeout is not None else 60.0
        self._client_factory = client_factory

        normalized_key = (private_key or "").strip()
        self._account = None
        self.account_address: Optional[str] = None

        if account is not None:
            self._account = account
            self.account_address = getattr(account, "address", None)
        elif normalized_key:
            if not normalized_key.startswith("0x") and all(
                ch in "0123456789abcdefABCDEF" for ch in normalized_key
            ):
                normalized_key = f"0x{normalized_key}"

            if Account is None:
                raise RuntimeError(
                    "eth-account is required for AIXBT payments. Install the optional dependency."
                )

            try:
                self._account = Account.from_key(normalized_key)
                self.account_address = self._account.address
            except Exception as exc:
                raise ValueError("Invalid AIXBT EVM private key") from exc

    @property
    def has_wallet(self) -> bool:
        return self._account is not None

    async def list_projects(
        self, params: Dict[str, Any]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        payload, _ = await self._request_json("GET", "/x402/v1/projects", params=params)
        data = payload.get("data", [])
        if not isinstance(data, list):
            raise AixbtError("Unexpected response format from AIXBT projects endpoint.")
        projects = [entry for entry in data if isinstance(entry, dict)]
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        return projects, meta

    async def query_indigo(self, messages: List[Dict[str, str]]) -> IndigoResult:
        payload, headers = await self._request_json(
            "POST", "/x402/agents/indigo", json_payload={"messages": messages}
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise AixbtError("Unexpected response format from AIXBT Indigo agent.")
        payment = self._parse_payment(headers)
        return IndigoResult(result=data, payment=payment)

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_payload: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        if x402HttpxClient is None or Account is None:
            raise AixbtError(
                "x402 python client is not installed. Run `pip install x402` to enable AIXBT tools."
            )
        if self._account is None:
            raise AixbtError(
                "AIXBT private key is not configured. Store it via secure storage or set AIXBT_PRIVATE_KEY."
            )

        full_path = path if path.startswith("/") else f"/{path}"

        if self._client_factory:
            client_ctx = self._client_factory(self._account, self._base_url, self._request_timeout)
        else:
            # Use our fixed x402 client that properly handles timeout during payment retry
            # The official x402HttpxClient has a bug where it creates a new AsyncClient
            # for retries without inheriting the timeout, causing ReadTimeout errors
            from sam.utils.x402_client_fixed import create_fixed_x402_client

            client_ctx = create_fixed_x402_client(
                account=self._account,
                base_url=self._base_url,
                timeout=self._request_timeout,
            )

        async with client_ctx as client:
            try:
                response = await client.request(
                    method.upper(),
                    full_path,
                    params=params or None,
                    json=json_payload or None,
                )
            except Exception as exc:  # pragma: no cover - network/runtime errors
                raise AixbtError(f"AIXBT request failed: {exc}") from exc

        status = response.status_code
        raw_headers = {key.lower(): value for key, value in response.headers.items()}

        try:
            payload = response.json()
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Invalid JSON from AIXBT API: %s", exc)
            raise AixbtError("AIXBT API returned invalid JSON") from exc

        if status >= 400:
            message = _extract_error(payload) or response.reason_phrase or f"HTTP {status}"
            raise AixbtError(f"AIXBT request failed: {message}")

        status_field = payload.get("status")
        if isinstance(status_field, int) and status_field != 200:
            raise AixbtError(
                _extract_error(payload) or f"AIXBT responded with status {status_field}"
            )

        return payload, raw_headers

    def _parse_payment(self, headers: Dict[str, str]) -> Optional[Dict[str, Any]]:
        header = headers.get("x-payment-response")
        if not header:
            return None
        try:
            decoded = base64.b64decode(header)
            text = decoded.decode("utf-8")
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:  # pragma: no cover - defensive against malformed headers
            logger.debug("Failed to decode x-payment-response header from AIXBT.", exc_info=True)
        return {"raw": header}


class AixbtTools:
    """High level wrappers that expose AIXBT capabilities as SAM tools."""

    def __init__(self, client: AixbtClient) -> None:
        self._client = client

    async def list_top_projects(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if not self._client.has_wallet:
            return {
                "error": "AIXBT_PRIVATE_KEY is not configured. Provide an EVM private key to authorize x402 payments."
            }

        filters = ProjectsInput(**args)
        params = filters.model_dump(by_alias=True, exclude_none=True)

        try:
            projects, meta = await self._client.list_projects(params)
        except AixbtError as exc:
            logger.error("AIXBT projects lookup failed: %s", exc)
            return {"error": str(exc)}

        summaries = [_summarize_project(project) for project in projects]
        return {
            "source": "aixbt",
            "filters": filters.model_dump(exclude_none=True),
            "count": len(projects),
            "projects": summaries,
            "meta": meta,
            "raw": projects,
        }

    async def indigo_research(self, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            payload = IndigoAgentInput(**args)
        except Exception as exc:
            return {"error": f"Validation failed: {exc}"}

        if not self._client.has_wallet:
            return {
                "error": "AIXBT_PRIVATE_KEY is not configured. Provide an EVM private key to authorize x402 payments."
            }

        messages = [message.model_dump() for message in payload.messages or []]

        try:
            result = await self._client.query_indigo(messages)
        except AixbtError as exc:
            logger.error("AIXBT Indigo request failed: %s", exc)
            return {"error": str(exc)}

        response = {
            "source": "aixbt",
            "messages": messages,
            "response": result.result,
        }
        text_block = result.result.get("text")
        if isinstance(text_block, str):
            response["response_text"] = text_block.strip()
        if result.payment:
            response["payment"] = result.payment
        return response


def create_aixbt_tools(tools: AixbtTools) -> List[Tool]:
    """Expose AIXBT tool definitions."""
    return [
        Tool(
            spec=ToolSpec(
                name="aixbt_projects",
                description=(
                    "List top crypto projects ranked by AIXBT intelligence signals. "
                    "Optionally filter by name, ticker, handle, minimum score, or sort preference."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 50,
                            "description": "Maximum number of results to return (default 25).",
                        },
                        "name": {"type": "string", "description": "Regex filter on project name."},
                        "ticker": {"type": "string", "description": "Exact ticker symbol filter."},
                        "x_handle": {
                            "type": "string",
                            "description": "Filter by associated X / Twitter handle.",
                        },
                        "sort_by": {
                            "type": "string",
                            "enum": ["score", "popularityScore"],
                            "description": "Order results by score (default) or popularity score.",
                        },
                        "min_score": {
                            "type": "number",
                            "minimum": 0,
                            "description": "Only include projects above this minimum score.",
                        },
                    },
                },
                namespace="aixbt",
            ),
            handler=tools.list_top_projects,
            input_model=ProjectsInput,
        ),
        Tool(
            spec=ToolSpec(
                name="aixbt_indigo_research",
                description=(
                    "Query the Indigo research agent for narrative analysis and market context. "
                    "Provide either a simple prompt or a structured list of chat messages."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "Optional single-turn prompt (messages field takes precedence).",
                        },
                        "messages": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "role": {
                                        "type": "string",
                                        "enum": ["system", "user", "assistant"],
                                    },
                                    "content": {"type": "string"},
                                },
                                "required": ["role", "content"],
                            },
                            "description": "Structured messages for multi-turn conversations.",
                        },
                    },
                },
                namespace="aixbt",
            ),
            handler=tools.indigo_research,
            input_model=IndigoAgentInput,
        ),
    ]
