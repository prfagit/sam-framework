import os
import sys
from pathlib import Path
import streamlit as st

# Make parent (app) directory importable when run via Streamlit
_PAGES_DIR = Path(__file__).resolve().parent
_APP_DIR = _PAGES_DIR.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))
from ui_shared import (  # noqa: E402
    inject_css,
    ensure_env_loaded,
    agent_ready_marker,
    run_sync,
    get_local_context,
)
from sam.config.settings import Settings  # noqa: E402
from sam.web.session import close_agent  # noqa: E402


st.set_page_config(page_title="Settings", page_icon="⚙️", layout="wide")
inject_css()
ensure_env_loaded()
agent_ready_marker()

st.title("⚙️ Settings")
st.caption("Provider and runtime configuration")

with st.form("provider_form"):
    providers = ["openai", "anthropic", "xai", "openai_compat", "local"]
    current_provider = (Settings.LLM_PROVIDER or "openai").lower()
    try:
        idx = providers.index(current_provider)
    except ValueError:
        idx = 0
    prov = st.selectbox("Provider", providers, index=idx)
    key = st.text_input("API Key", type="password")
    base = st.text_input("Base URL (optional)")
    submitted = st.form_submit_button("Save", use_container_width=False)

    if submitted:
        from sam.utils.env_files import find_env_path, write_env_file

        env_path = find_env_path()
        current = {}
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                for line in f:
                    if "=" in line and not line.strip().startswith("#"):
                        k, v = line.strip().split("=", 1)
                        current[k] = v

        current["LLM_PROVIDER"] = prov
        if prov == "openai":
            if key:
                current["OPENAI_API_KEY"] = key
            if base:
                current["OPENAI_BASE_URL"] = base
        elif prov == "anthropic":
            if key:
                current["ANTHROPIC_API_KEY"] = key
            if base:
                current["ANTHROPIC_BASE_URL"] = base
        elif prov == "xai":
            if key:
                current["XAI_API_KEY"] = key
            if base:
                current["XAI_BASE_URL"] = base
        elif prov == "openai_compat":
            if base:
                current["OPENAI_BASE_URL"] = base
            if key:
                current["OPENAI_API_KEY"] = key
        elif prov == "local":
            if base:
                current["LOCAL_LLM_BASE_URL"] = base
            if key:
                current["LOCAL_LLM_API_KEY"] = key

        write_env_file(env_path, current)
        ensure_env_loaded()
        st.success("Saved. Click 'Reset Agent' to apply.")

st.divider()

# Agent + Tools configuration (mirrors CLI toggles)
with st.form("agent_form"):
    st.subheader("Agent")
    rpc = st.text_input("Solana RPC URL", value=Settings.SAM_SOLANA_RPC_URL or "")
    db_path = st.text_input("DB Path", value=Settings.SAM_DB_PATH or ".sam/sam_memory.db")
    rate_limit = st.checkbox("Enable Rate Limiting", value=bool(Settings.RATE_LIMITING_ENABLED))
    log_level = st.selectbox(
        "Log Level",
        ["NO", "ERROR", "WARNING", "INFO", "DEBUG"],
        index=["NO", "ERROR", "WARNING", "INFO", "DEBUG"].index(
            (Settings.LOG_LEVEL or "INFO").upper()
        ),
    )

    st.subheader("Safety")
    max_tx = st.number_input(
        "Max Transaction (SOL)",
        min_value=0.0,
        max_value=100000.0,
        value=float(Settings.MAX_TRANSACTION_SOL or 1000.0),
        step=0.1,
    )
    slippage = st.number_input(
        "Default Slippage (%)",
        min_value=0,
        max_value=100,
        value=int(Settings.DEFAULT_SLIPPAGE or 1),
        step=1,
    )

    submitted_agent = st.form_submit_button("Save Settings")
    if submitted_agent:
        from sam.utils.env_files import find_env_path, write_env_file

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
                "SAM_SOLANA_RPC_URL": rpc,
                "SAM_DB_PATH": db_path,
                "RATE_LIMITING_ENABLED": "true" if rate_limit else "false",
                "LOG_LEVEL": log_level,
                "MAX_TRANSACTION_SOL": str(max_tx),
                "DEFAULT_SLIPPAGE": str(int(slippage)),
            }
        )

        write_env_file(env_path, current)
        ensure_env_loaded()
        st.success("Saved. Click 'Reset Agent' to apply.")

if st.button("Reset Agent", use_container_width=False):
    run_sync(close_agent(get_local_context()))
    st.cache_resource.clear()
    st.success("Agent reset. Return to Chat.")
