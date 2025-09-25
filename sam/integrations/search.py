"""Search Tools Integration for SAM Framework."""

import logging
import os
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from ..core.tools import Tool, ToolSpec

# Decorators replaced by registry middlewares for rate limit/retry/logging
from ..utils.http_client import get_session

logger = logging.getLogger(__name__)


class SearchTools:
    """Search functionality using Brave search API."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        """Initialize search tools with optional Brave API key."""
        self.api_key = api_key or os.getenv("BRAVE_API_KEY")
        logger.info(
            f"Initialized search tools {'with API key' if self.api_key else 'with fallback mode'}"
        )

    async def close(self) -> None:
        """Close method for compatibility - shared client handles cleanup."""
        pass  # Shared HTTP client handles session lifecycle

    async def search_web(
        self, query: str, count: int = 5, freshness: Optional[str] = None
    ) -> Dict[str, Any]:
        """Search the web using Brave search API."""
        if not self.api_key:
            return {
                "error": "Brave Search API key is required. Set BRAVE_API_KEY environment variable."
            }

        try:
            return await self._brave_api_search(query, count, "web", freshness)

        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return {"error": str(e)}

    async def search_news(
        self, query: str, count: int = 5, freshness: Optional[str] = "pw"
    ) -> Dict[str, Any]:
        """Search for news using Brave search API."""
        if not self.api_key:
            return {
                "error": "Brave Search API key is required. Set BRAVE_API_KEY environment variable."
            }

        try:
            return await self._brave_api_search(query, count, "news", freshness)

        except Exception as e:
            logger.error(f"News search failed: {e}")
            return {"error": str(e)}

    async def _brave_api_search(
        self, query: str, count: int, search_type: str, freshness: Optional[str] = None
    ) -> Dict[str, Any]:
        """Search using Brave Search API."""
        try:
            session = await get_session()

            url = "https://api.search.brave.com/res/v1/web/search"
            if search_type == "news":
                url = "https://api.search.brave.com/res/v1/news/search"

            headers = {"Accept": "application/json", "X-Subscription-Token": self.api_key or ""}

            params: Dict[str, Any] = {"q": query, "count": min(count, 20)}

            if freshness:
                params["freshness"] = freshness

            async with session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()

                    results: List[Dict[str, str]] = []
                    containers = data.get("web", {}) if search_type == "web" else data
                    raw_results = (
                        containers.get("results", []) if isinstance(containers, dict) else []
                    )

                    for result in raw_results:
                        if not isinstance(result, dict):
                            continue
                        results.append(
                            {
                                "title": str(result.get("title", "")),
                                "url": str(result.get("url", "")),
                                "description": str(result.get("description", "")),
                                "published": str(result.get("age", "")),
                            }
                        )

                    logger.info(f"Brave API {search_type} search completed for: {query}")
                    return {
                        "query": query,
                        "type": search_type,
                        "results": results,
                        "count": len(results),
                    }
                else:
                    error_text = await response.text()
                    logger.error(f"Brave API error {response.status}: {error_text}")
                    return {"error": f"Brave Search API error {response.status}: {error_text}"}

        except Exception as e:
            logger.error(f"Network or unexpected error in {search_type} search: {e}")
            return {"error": f"Search failed: {str(e)}"}


def create_search_tools(search_tools: SearchTools) -> List[Tool]:
    """Create search tool instances."""

    # Optional input models for decentralized validation
    class WebSearchInput(BaseModel):
        query: str = Field(..., description="Search query terms")
        count: int = Field(5, ge=1, le=10, description="Number of results to return (1-10)")
        freshness: Optional[str] = Field(
            None,
            description="Time filter: 'pd' (day), 'pw' (week), 'pm' (month), 'py' (year)",
        )

        @field_validator("freshness")
        @classmethod
        def validate_freshness(
            cls, value: Optional[str]
        ) -> Optional[str]:  # pragma: no cover - simple input validation
            if value is not None and value not in {"pd", "pw", "pm", "py"}:
                raise ValueError("freshness must be one of: pd, pw, pm, py")
            return value

    class NewsSearchInput(BaseModel):
        query: str = Field(..., description="News search query")
        count: int = Field(5, ge=1, le=10, description="Number of results to return (1-10)")
        freshness: str = Field(
            "pw", description="Time filter: 'pd' (day), 'pw' (week), 'pm' (month)"
        )

        @field_validator("freshness")
        @classmethod
        def validate_freshness(cls, value: str) -> str:  # pragma: no cover - simple input validation
            if value not in {"pd", "pw", "pm"}:
                raise ValueError("freshness must be one of: pd, pw, pm")
            return value

    async def handle_web_search(args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle web search requests."""
        query = args.get("query", "")
        if not query:
            return {"error": "Search query is required"}

        count_value = args.get("count", 5)
        count = int(count_value) if isinstance(count_value, int) else 5
        freshness_value = args.get("freshness")
        freshness = str(freshness_value) if isinstance(freshness_value, str) else None

        return await search_tools.search_web(query, count, freshness)

    async def handle_news_search(args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle news search requests."""
        query = args.get("query", "")
        if not query:
            return {"error": "Search query is required"}

        count_value = args.get("count", 5)
        count = int(count_value) if isinstance(count_value, int) else 5
        freshness_value = args.get("freshness", "pw")
        freshness = str(freshness_value) if isinstance(freshness_value, str) else "pw"

        return await search_tools.search_news(query, count, freshness)

    tools = [
        Tool(
            spec=ToolSpec(
                name="search_web",
                description="Search the internet for current information, websites, and general content",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query terms"},
                        "count": {
                            "type": "integer",
                            "description": "Number of results to return (1-10)",
                            "minimum": 1,
                            "maximum": 10,
                            "default": 5,
                        },
                        "freshness": {
                            "type": "string",
                            "description": "Filter by time period: 'pd' (past day), 'pw' (past week), 'pm' (past month), 'py' (past year)",
                            "enum": ["pd", "pw", "pm", "py"],
                        },
                    },
                    "required": ["query"],
                },
            ),
            handler=handle_web_search,
            input_model=WebSearchInput,
        ),
        Tool(
            spec=ToolSpec(
                name="search_news",
                description="Search for recent news articles and current events",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "News search query"},
                        "count": {
                            "type": "integer",
                            "description": "Number of news articles to return (1-10)",
                            "minimum": 1,
                            "maximum": 10,
                            "default": 5,
                        },
                        "freshness": {
                            "type": "string",
                            "description": "Time period for news: 'pd' (past day), 'pw' (past week), 'pm' (past month)",
                            "enum": ["pd", "pw", "pm"],
                            "default": "pw",
                        },
                    },
                    "required": ["query"],
                },
            ),
            handler=handle_news_search,
            input_model=NewsSearchInput,
        ),
    ]

    return tools
