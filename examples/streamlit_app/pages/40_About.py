import sys
from pathlib import Path
import streamlit as st

_PAGES_DIR = Path(__file__).resolve().parent
_APP_DIR = _PAGES_DIR.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))
from ui_shared import inject_css  # noqa: E402

st.set_page_config(page_title="About", page_icon="ℹ️", layout="wide")
inject_css()

st.title("ℹ️ About")
st.caption("SAM — Solana Agent Middleware")
st.write("Minimal chat UI with separate pages for settings and wallet.")
