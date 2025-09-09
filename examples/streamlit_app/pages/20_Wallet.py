import sys
from pathlib import Path
import streamlit as st

# Ensure parent directory import for shared UI helpers
_PAGES_DIR = Path(__file__).resolve().parent
_APP_DIR = _PAGES_DIR.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))
from ui_shared import inject_css, ensure_env_loaded, agent_ready_marker, run_sync  # noqa: E402
from sam.web.session import get_agent  # noqa: E402


st.set_page_config(page_title="Wallet", page_icon="👛", layout="wide")
inject_css()
ensure_env_loaded()
agent_ready_marker()

st.title("👛 Wallet")
st.caption("Current wallet and balances")

try:
    agent = run_sync(get_agent())
except Exception as e:
    agent = None
    st.error(f"Failed to initialize agent: {e}")

sol_tools = getattr(agent, "_solana_tools", None) if agent else None
wallet = getattr(sol_tools, "wallet_address", None)

st.write(f"Address: {wallet or 'unset'}")

if st.button("Check Balance", use_container_width=False):
    if not sol_tools:
        st.warning("Solana tools are disabled or unavailable.")
    else:
        try:
            result = run_sync(sol_tools.get_balance())
            if isinstance(result, dict):
                if "error" in result:
                    st.warning(result.get("error") or "Unknown error")
                else:
                    st.json(result)
            else:
                st.info("No balance data returned.")
        except Exception as e:
            st.error(str(e))
