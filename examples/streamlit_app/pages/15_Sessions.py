import streamlit as st

from ui_shared import inject_css, ensure_env_loaded, ensure_session_init, run_sync
from sam.web.session import list_sessions, new_session_id, clear_all_sessions


st.set_page_config(page_title="Sessions • SAM", page_icon="🗂️", layout="wide")

inject_css()
ensure_session_init()
ensure_env_loaded()


st.title("🗂️ Sessions")
st.caption("Manage and switch between saved conversations")

# Fetch sessions
try:
    data = run_sync(list_sessions(limit=100))
except Exception:
    data = []

current_sid = st.session_state.get("session_id")

colA, colB, colC = st.columns([1, 1, 3])
with colA:
    if st.button("🆕 New Session"):
        try:
            sid = run_sync(new_session_id())
            st.session_state["session_id"] = sid
        except Exception:
            pass
        st.session_state["messages"] = []
        st.session_state["history_loaded"] = False
        st.rerun()
with colB:
    if st.button("🧨 Clear All Sessions"):
        try:
            _ = run_sync(clear_all_sessions())
            sid = run_sync(new_session_id())
            st.session_state["session_id"] = sid
        except Exception:
            pass
        st.session_state["messages"] = []
        st.session_state["history_loaded"] = False
        st.rerun()
with colC:
    st.info(f"Active session: {current_sid}")

st.divider()

if not data:
    st.write("No saved sessions yet.")
else:
    # Build selection list
    labels = []
    sid_map = {}
    for s in data:
        sid = s.get("session_id")
        label = f"{sid}  •  msgs:{s.get('message_count',0)}  •  updated:{s.get('updated_at','')}"
        labels.append(label)
        sid_map[label] = sid

    default_index = 0
    try:
        current_label = next(l for l, sid in sid_map.items() if sid == current_sid)
        default_index = labels.index(current_label)
    except Exception:
        pass

    choice = st.radio("Choose a session to activate:", labels, index=default_index)

    c1, c2 = st.columns([1, 5])
    with c1:
        if st.button("Set Active"):
            sel_sid = sid_map.get(choice)
            if sel_sid and sel_sid != current_sid:
                st.session_state["session_id"] = sel_sid
                st.session_state["messages"] = []
                st.session_state["history_loaded"] = False
                st.rerun()
    with c2:
        st.caption("Tip: go back to the Chat page to continue the conversation.")

