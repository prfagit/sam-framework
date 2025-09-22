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
from sam.config.settings import Settings  # noqa: E402
from sam.utils.env_files import find_env_path, write_env_file  # noqa: E402
import os  # noqa: E402


st.set_page_config(page_title="Tools", page_icon="🛠️", layout="wide")
inject_css()
ensure_env_loaded()
agent_ready_marker()

st.title("🛠️ Tools")
st.caption("Enable/disable tool integrations and view registered tools")

with st.form("tools_form"):
    t_solana = st.checkbox("Solana Tools", value=bool(Settings.ENABLE_SOLANA_TOOLS))
    t_pump = st.checkbox("Pump.fun Tools", value=bool(Settings.ENABLE_PUMP_FUN_TOOLS))
    t_dex = st.checkbox("DexScreener Tools", value=bool(Settings.ENABLE_DEXSCREENER_TOOLS))
    t_jup = st.checkbox("Jupiter Tools", value=bool(Settings.ENABLE_JUPITER_TOOLS))
    t_poly = st.checkbox("Polymarket Tools", value=bool(Settings.ENABLE_POLYMARKET_TOOLS))
    t_search = st.checkbox("Web Search Tools", value=bool(Settings.ENABLE_SEARCH_TOOLS))
    saved = st.form_submit_button("Save")
    if saved:
        env_path = find_env_path()
        current = {}
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                for line in f:
                    if "=" in line and not line.strip().startswith("#"):
                        k, v = line.strip().split("=", 1)
                        current[k] = v
        current.update(
            {
                "ENABLE_SOLANA_TOOLS": "true" if t_solana else "false",
                "ENABLE_PUMP_FUN_TOOLS": "true" if t_pump else "false",
                "ENABLE_DEXSCREENER_TOOLS": "true" if t_dex else "false",
                "ENABLE_JUPITER_TOOLS": "true" if t_jup else "false",
                "ENABLE_POLYMARKET_TOOLS": "true" if t_poly else "false",
                "ENABLE_SEARCH_TOOLS": "true" if t_search else "false",
            }
        )
        write_env_file(env_path, current)
        st.success("Saved. Restart agent to apply.")

st.divider()

agent = run_sync(get_agent())
specs = agent.tools.list_specs()
st.subheader("Registered Tools")
for s in sorted(specs, key=lambda x: x.get("name", "")):
    st.write(f"- {s.get('name')} — {s.get('description', '')}")
