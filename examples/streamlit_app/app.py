import streamlit as st
import sys
from pathlib import Path

from sam.web.session import run_with_events, run_once, get_agent

# Ensure local module imports work when run via `streamlit run`
_APP_DIR = Path(__file__).resolve().parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))
from ui_shared import (  # noqa: E402
    inject_css,
    ensure_env_loaded,
    ensure_session_init,
    agent_ready_marker,
    run_sync,
    get_local_context,
)


st.set_page_config(
    page_title="SAM Chat", page_icon="🤖", layout="wide", initial_sidebar_state="expanded"
)

inject_css()
ensure_session_init()
ensure_env_loaded()
agent_ready_marker()


def render_chat():
    col1, col2 = st.columns([6, 2])
    with col1:
        st.title("🤖 SAM Agent")
        st.caption("Solana Agent Middleware — Chat")
        # Show active session id inline (no sidebar)
        try:
            st.caption(f"Session: {st.session_state['session_id']}")
        except Exception:
            pass
    with col2:
        if st.button("🗑️ Clear Chat"):

            async def _clear():
                from sam.web.session import get_agent

                agent = await get_agent(get_local_context())
                await agent.clear_context(
                    st.session_state["session_id"],
                    user_id=get_local_context().user_id,
                )  # type: ignore

            try:
                run_sync(_clear())
            except Exception:
                pass
            st.session_state["messages"] = []
            st.session_state["processing"] = False
            try:
                st.rerun()
            except Exception:
                pass

    # No sidebar session management; see Sessions page instead

    # Load history from memory if not yet loaded
    if not st.session_state.get("history_loaded"):

        async def _load_history():
            from sam.web.session import get_agent

            agent = await get_agent(get_local_context())
            msgs = await agent.memory.load_session(  # type: ignore
                st.session_state["session_id"],
                user_id=get_local_context().user_id,
            )
            # Convert stored context to chat-friendly subset
            ui_msgs = []
            for m in msgs:
                role = m.get("role")
                content = m.get("content", "")
                if role in {"user", "assistant"} and content:
                    ui_msgs.append({"role": role, "content": content})
            return ui_msgs

        try:
            hist = run_sync(_load_history())
        except Exception:
            hist = []
        if hist:
            # Only load history if messages is empty to prevent duplication
            if not st.session_state["messages"]:
                st.session_state["messages"] = hist
        st.session_state["history_loaded"] = True

    # Normalize history: drop consecutive duplicate messages (same role + normalized content)
    if st.session_state.get("messages"):
        msgs = st.session_state["messages"]

        def _norm(txt: str) -> str:
            try:
                return " ".join((txt or "").split())
            except Exception:
                return txt or ""

        deduped = []
        for m in msgs:
            role = m.get("role")
            content = _norm(m.get("content", ""))
            if deduped:
                prev = deduped[-1]
                if prev.get("role") == role and _norm(prev.get("content", "")) == content:
                    continue
            deduped.append(m)
        if len(deduped) != len(msgs):
            st.session_state["messages"] = deduped

    # Render all messages from state, handling special streaming case
    for i, m in enumerate(st.session_state["messages"]):
        with st.chat_message(m["role"]):
            # If this is the last message and it's empty (streaming placeholder)
            if (
                i == len(st.session_state["messages"]) - 1
                and m["role"] == "assistant"
                and not m.get("content", "").strip()
            ):
                # This is the active streaming placeholder
                status_box = st.empty()
                events_box = st.empty()
                placeholder = st.empty()

                # Get the user input that triggered this response
                current_input = st.session_state.get("last_input")
                if current_input:

                    async def _do_stream():
                        assistant_text = ""
                        event_log_html = ""
                        status_box.markdown(
                            "<span class='sam-spinner'></span> Thinking",
                            unsafe_allow_html=True,
                        )
                        async with run_with_events(
                            current_input,
                            st.session_state["session_id"],
                            context=get_local_context(),
                        ) as events:
                            async for evt in events:
                                name = evt.get("event")
                                payload = evt.get("payload", {})
                                if name == "agent.status":
                                    msg = payload.get("message", "")
                                    status_box.markdown(
                                        f"<span class='sam-spinner'></span> {msg}",
                                        unsafe_allow_html=True,
                                    )
                                    continue
                                if name == "agent.delta":
                                    assistant_text += payload.get("content", "")
                                    placeholder.markdown(
                                        f"<div class='typing-cursor'>{assistant_text}</div>",
                                        unsafe_allow_html=True,
                                    )
                                elif name == "tool.called":
                                    tname = payload.get("name", "tool")
                                    args = payload.get("args", {})
                                    event_log_html += f"<div class='tool-event'><strong>Tool:</strong> {tname} &nbsp; <strong>args:</strong> {args}</div>"
                                    events_box.markdown(event_log_html, unsafe_allow_html=True)
                                elif name == "tool.succeeded":
                                    tname = payload.get("name", "tool")
                                    event_log_html += f"<div class='tool-event'><strong>Success:</strong> {tname}</div>"
                                    events_box.markdown(event_log_html, unsafe_allow_html=True)
                                elif name == "tool.failed":
                                    tname = payload.get("name", "tool")
                                    err = payload.get("error", "")
                                    event_log_html += f"<div class='tool-event'><strong>Failed:</strong> {tname} &nbsp; <span>{err}</span></div>"
                                    events_box.markdown(event_log_html, unsafe_allow_html=True)
                                elif name == "llm.usage":
                                    usage = payload.get("usage", {})
                                    tt = usage.get("total_tokens", "?")
                                    pt = usage.get("prompt_tokens", "?")
                                    ct = usage.get("completion_tokens", "?")
                                    event_log_html += f"<div class='tool-event'><strong>LLM:</strong> tokens p/c/t = {pt}/{ct}/{tt}</div>"
                                    events_box.markdown(event_log_html, unsafe_allow_html=True)
                                elif name == "agent.message":
                                    assistant_text = payload.get("content", assistant_text)
                                    placeholder.markdown(assistant_text)
                                    status_box.empty()
                        return assistant_text

                    try:
                        reply = run_sync(_do_stream())
                    except Exception:
                        reply = run_once(
                            current_input,
                            st.session_state["session_id"],
                            context=get_local_context(),
                        )  # type: ignore

                    # Update the message in state with the final response
                    if reply is not None:
                        st.session_state["messages"][i]["content"] = reply
                        st.session_state["last_input"] = None  # Clear to prevent reprocessing

                        # If previous assistant message has identical content, drop this one
                        def _norm(txt: str) -> str:
                            try:
                                return " ".join((txt or "").split())
                            except Exception:
                                return txt or ""

                        prev_assistant_idx = None
                        for j in range(i - 1, -1, -1):
                            if st.session_state["messages"][j].get("role") == "assistant":
                                prev_assistant_idx = j
                                break
                        if prev_assistant_idx is not None:
                            prev_content = _norm(
                                st.session_state["messages"][prev_assistant_idx].get(
                                    "content", ""
                                )
                            )
                            if _norm(reply) == prev_content:
                                # Remove the duplicate last assistant message and rerun
                                st.session_state["messages"].pop(i)
                                st.session_state["processing"] = False
                                st.rerun()
                                return

                    # Always clear processing flag after stream completes
                    st.session_state["processing"] = False
            else:
                st.markdown(m["content"])

    user_input = st.chat_input("Ask SAM…", disabled=st.session_state.get("processing", False))
    if not user_input:
        return

    # Check if this is a new input to prevent reprocessing
    if user_input == st.session_state.get("last_input"):
        return

    # Handle slash commands BEFORE adding to history
    if user_input.strip().startswith("/"):
        cmd = user_input.strip().lstrip("/").lower()
        if cmd in {"settings", "config"}:
            st.switch_page("pages/settings.py")
            return
        if cmd in {"wallet"}:
            st.switch_page("pages/wallet.py")
            return
        if cmd in {"tools"}:
            st.switch_page("pages/tools.py")
            return
        if cmd in {"sessions", "session"}:
            st.switch_page("pages/sessions.py")
            return
        if cmd in {"clear", "new", "reset"}:
            # Clear conversation context (DB + UI)
            async def _clear():
                agent = await get_agent()
                await agent.clear_context(
                    st.session_state["session_id"],
                    user_id=get_local_context().user_id,
                )  # type: ignore

            try:
                run_sync(_clear())
            except Exception:
                pass
            st.session_state["messages"] = []
            st.session_state["messages"].append(
                {"role": "assistant", "content": "Context cleared. Starting fresh."}
            )
            st.session_state["last_input"] = None
            st.rerun()
            return

    # Store the current input and add to history
    st.session_state["last_input"] = user_input
    st.session_state["messages"].append({"role": "user", "content": user_input})

    # Add placeholder for assistant response
    st.session_state["messages"].append({"role": "assistant", "content": ""})
    # Mark processing to disable input while streaming
    st.session_state["processing"] = True

    # Rerun to show the user message in history and trigger streaming
    st.rerun()


render_chat()
