import asyncio
from pathlib import Path
from uuid import uuid4
import streamlit as st

from sam.web.session import get_agent
from sam.config.settings import Settings


def inject_css():
    css_path = Path(__file__).parent / "styles.css"
    try:
        css = css_path.read_text(encoding="utf-8")
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    except Exception:
        pass


def ensure_env_loaded():
    from sam.utils.env_files import find_env_path
    from dotenv import load_dotenv

    env_path = find_env_path()
    load_dotenv(env_path, override=True)
    Settings.refresh_from_env()


def ensure_session_init():
    if "messages" not in st.session_state:
        st.session_state["messages"] = []
    # Generate a stable, per-session id to avoid shared conversations
    if "session_id" not in st.session_state or not st.session_state["session_id"]:
        st.session_state["session_id"] = str(uuid4())
    if "agent_ready" not in st.session_state:
        st.session_state["agent_ready"] = False
    if "last_input" not in st.session_state:
        st.session_state["last_input"] = None
    if "history_loaded" not in st.session_state:
        st.session_state["history_loaded"] = False


def run_sync(coro):
    """Run an async coroutine in both fresh and existing event loop contexts."""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coro)


@st.cache_resource(show_spinner=False)
def agent_ready_marker() -> bool:
    async def _build():
        await get_agent()

    run_sync(_build())
    return True
