"""Search Tools Integration for SAM Framework."""

import logging
import aiohttp
import asyncio
import os
from typing import Dict, Any, List, Optional
from ..core.tools import Tool, ToolSpec
from ..utils.decorators import rate_limit, retry_with_backoff, log_execution

logger = logging.getLogger(__name__)


class SearchTools:
    """Search functionality using Brave search API."""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize search tools with optional Brave API key."""
        self.api_key = api_key or os.getenv("BRAVE_API_KEY")
        self.session = None
        logger.info(f"Initialized search tools {'with API key' if self.api_key else 'with fallback mode'}")
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session
    
    async def close(self):
        """Close HTTP session."""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("Closed search tools session")
    
    @rate_limit("search")
    @retry_with_backoff(max_retries=2) 
    @log_execution()
    async def search_web(self, query: str, count: int = 5, freshness: str = None) -> Dict[str, Any]:
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
    
    @rate_limit("search")
    @retry_with_backoff(max_retries=2)
    @log_execution() 
    async def search_news(self, query: str, count: int = 5, freshness: str = "pw") -> Dict[str, Any]:
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
    
    async def _brave_api_search(self, query: str, count: int, search_type: str, freshness: str = None) -> Dict[str, Any]:
        """Search using Brave Search API."""
        session = await self._get_session()
        
        url = "https://api.search.brave.com/res/v1/web/search"
        if search_type == "news":
            url = "https://api.search.brave.com/res/v1/news/search"
        
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self.api_key
        }
        
        params = {
            "q": query,
            "count": min(count, 20)
        }
        
        if freshness:
            params["freshness"] = freshness
        
        async with session.get(url, headers=headers, params=params) as response:
            if response.status == 200:
                data = await response.json()
                
                results = []
                web_results = data.get("web", {}).get("results", []) if search_type == "web" else data.get("results", [])
                
                for result in web_results:
                    results.append({
                        "title": result.get("title", ""),
                        "url": result.get("url", ""),
                        "description": result.get("description", ""),
                        "published": result.get("age", "")
                    })
                
                logger.info(f"Brave API {search_type} search completed for: {query}")
                return {
                    "query": query,
                    "type": search_type,
                    "results": results,
                    "count": len(results)
                }
            else:
                error_text = await response.text()
                logger.error(f"Brave API error {response.status}: {error_text}")
                return {
                    "error": f"Brave Search API error {response.status}: {error_text}"
                }
    


def create_search_tools(search_tools: SearchTools) -> List[Tool]:
    """Create search tool instances."""
    
    async def handle_web_search(args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle web search requests."""
        query = args.get("query", "")
        if not query:
            return {"error": "Search query is required"}
        
        count = args.get("count", 5)
        freshness = args.get("freshness")
        
        return await search_tools.search_web(query, count, freshness)
    
    async def handle_news_search(args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle news search requests.""" 
        query = args.get("query", "")
        if not query:
            return {"error": "Search query is required"}
        
        count = args.get("count", 5)
        freshness = args.get("freshness", "pw")
        
        return await search_tools.search_news(query, count, freshness)
    
    tools = [
        Tool(
            spec=ToolSpec(
                name="search_web",
                description="Search the internet for current information, websites, and general content",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query terms"
                        },
                        "count": {
                            "type": "integer", 
                            "description": "Number of results to return (1-10)",
                            "minimum": 1,
                            "maximum": 10,
                            "default": 5
                        },
                        "freshness": {
                            "type": "string",
                            "description": "Filter by time period: 'pd' (past day), 'pw' (past week), 'pm' (past month), 'py' (past year)",
                            "enum": ["pd", "pw", "pm", "py"]
                        }
                    },
                    "required": ["query"]
                }
            ),
            handler=handle_web_search
        ),
        Tool(
            spec=ToolSpec(
                name="search_news", 
                description="Search for recent news articles and current events",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "News search query"
                        },
                        "count": {
                            "type": "integer",
                            "description": "Number of news articles to return (1-10)",
                            "minimum": 1,
                            "maximum": 10, 
                            "default": 5
                        },
                        "freshness": {
                            "type": "string",
                            "description": "Time period for news: 'pd' (past day), 'pw' (past week), 'pm' (past month)",
                            "enum": ["pd", "pw", "pm"],
                            "default": "pw"
                        }
                    },
                    "required": ["query"]
                }
            ),
            handler=handle_news_search
        )
    ]
    
    return tools