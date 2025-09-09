"""Web adapter utilities for GUI frontends.

This module provides integration utilities for web-based frontends
like Streamlit to interact with the SAM agent framework.
"""

from .session import get_agent, close_agent, run_once, run_with_events

__all__ = ["get_agent", "close_agent", "run_once", "run_with_events"]
