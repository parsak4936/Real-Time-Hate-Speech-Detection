"""
Analyst chat — Streamlit UI wrapping the Leader Agent.

NOT a chat UI for end users. This is for the *moderator/operator*: a nicer
front-end on top of `src/agents/leader_agent.py` so the analyst can query
the pipeline in natural language without a terminal.

Distinction from `scripts/operator_dashboard.py`:
  - dashboard       = passive monitoring  (open, leave running)
  - this chat       = active query        (open, ask, get answer)

Tool-call transparency: every analyst message is decomposed into
  Phase 1 — router LLM picks a tool + params (shown in an expander)
  Phase 2 — tool runs against ES (raw output shown in an expander)
  Phase 3 — synthesis LLM summarises (the visible chat reply)

Conversations persist across sessions: each chat is saved to a JSON file
in `chat_history/` so you can switch between them via the sidebar.

Run:
    streamlit run scripts/analyst_chat.py

Opens at http://localhost:8501. If the operator dashboard is already
running on 8501, start this one on 8502:
    streamlit run scripts/analyst_chat.py --server.port 8502
"""

from __future__ import annotations

import datetime
import json
import re
import sys
import uuid
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from elasticsearch import Elasticsearch

from shared_utils.config import ES_HOST, INDEX_NAME, ACTIVE_MODEL
from shared_utils.llm import ollama_chat_json, ollama_chat_text
from shared_utils.prompts import (
    build_leader_router_prompt,
    build_leader_synthesis_prompt,
)
from agents.tools.search_tool import execute_universal_search
from agents.tools.stats_tool import execute_statistics
from agents.tools.weather_tool import execute_weather_time
from agents.tools.xai_judge_tool import execute_xai_judge


TOOL_REGISTRY = {
    "UNIVERSAL_SEARCH": execute_universal_search,
    "GET_STATISTICS": execute_statistics,
    "GET_WEATHER": execute_weather_time,
    "XAI_JUDGE": execute_xai_judge,
}

CHAT_HISTORY_DIR = ROOT / "chat_history"
CHAT_HISTORY_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Conversation persistence
# ---------------------------------------------------------------------------

def _slugify(text: str, max_len: int = 40) -> str:
    """Make a short filesystem-safe slug from the first user message."""
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    return text[:max_len] or "conversation"


def list_conversations():
    """Return [(filepath, metadata_dict), ...] sorted by updated_at desc."""
    items = []
    for fp in CHAT_HISTORY_DIR.glob("*.json"):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            items.append((fp, data))
        except Exception:
            continue
    items.sort(key=lambda x: x[1].get("updated_at", ""), reverse=True)
    return items


def new_conversation_id() -> str:
    return f"chat_{datetime.datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"


def save_active_conversation():
    """Persist the active conversation to its file."""
    if not st.session_state.messages:
        return
    convo_id = st.session_state.active_convo_id
    fp = CHAT_HISTORY_DIR / f"{convo_id}.json"

    # First user message becomes the title slug.
    first_user = next(
        (m["content"] for m in st.session_state.messages if m["role"] == "user"),
        "untitled",
    )
    title = st.session_state.get("active_convo_title") or first_user[:60]

    data = {
        "id":         convo_id,
        "title":      title,
        "model":      ACTIVE_MODEL,
        "created_at": st.session_state.get("active_convo_created_at",
                                           datetime.datetime.now().isoformat()),
        "updated_at": datetime.datetime.now().isoformat(),
        "messages":   st.session_state.messages,
    }
    fp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    st.session_state.active_convo_title = title


def load_conversation(fp: Path):
    data = json.loads(fp.read_text(encoding="utf-8"))
    st.session_state.messages = data.get("messages", [])
    st.session_state.active_convo_id = data.get("id", fp.stem)
    st.session_state.active_convo_title = data.get("title", fp.stem)
    st.session_state.active_convo_created_at = data.get(
        "created_at", datetime.datetime.now().isoformat()
    )


def start_new_conversation():
    st.session_state.messages = []
    st.session_state.active_convo_id = new_conversation_id()
    st.session_state.active_convo_title = None
    st.session_state.active_convo_created_at = datetime.datetime.now().isoformat()


def delete_conversation(fp: Path):
    try:
        fp.unlink()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Moderator Analyst Chat",
    layout="wide",
)


@st.cache_data(ttl=30)
def get_db_schema():
    try:
        es = Elasticsearch(ES_HOST, request_timeout=3)
        res = es.search(index=INDEX_NAME, size=1)
        if res["hits"]["hits"]:
            return list(res["hits"]["hits"][0]["_source"].keys())
        return ["(no records in index yet)"]
    except Exception as exc:
        return [f"(ES unreachable: {str(exc)[:60]})"]


# ---------------------------------------------------------------------------
# Session state init
# ---------------------------------------------------------------------------

if "messages" not in st.session_state:
    st.session_state.messages = []
if "active_convo_id" not in st.session_state:
    st.session_state.active_convo_id = new_conversation_id()
if "active_convo_title" not in st.session_state:
    st.session_state.active_convo_title = None
if "active_convo_created_at" not in st.session_state:
    st.session_state.active_convo_created_at = datetime.datetime.now().isoformat()
if "schema" not in st.session_state:
    st.session_state.schema = get_db_schema()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("Moderator Chat")
    st.caption("Ask in plain English. The AI will figure out the query.")

    if st.button("➕ New conversation", use_container_width=True, type="primary"):
        start_new_conversation()
        st.rerun()

    st.divider()
    st.subheader("Past conversations")
    convos = list_conversations()
    if not convos:
        st.caption("_No saved conversations yet. Start chatting and they appear here._")
    else:
        active_id = st.session_state.active_convo_id
        for fp, meta in convos[:30]:
            convo_id = meta.get("id", fp.stem)
            title = meta.get("title", fp.stem) or fp.stem
            updated = meta.get("updated_at", "")[:16].replace("T", " ")
            is_active = convo_id == active_id

            col_load, col_del = st.columns([5, 1])
            with col_load:
                label = ("🟢 " if is_active else "") + title[:42]
                if st.button(label, key=f"load_{convo_id}", use_container_width=True,
                             help=f"Updated {updated}"):
                    load_conversation(fp)
                    st.rerun()
            with col_del:
                if st.button("🗑", key=f"del_{convo_id}", help="Delete"):
                    delete_conversation(fp)
                    if is_active:
                        start_new_conversation()
                    st.rerun()

    st.divider()
    st.subheader("Try asking…")
    example_groups = {
        "Counts": [
            "how many records do we have",
            "how many from twitch",
            "how many were reviewed by the AI",
        ],
        "Worst behaviour": [
            "who are the most toxic users",
            "top toxic users on youtube",
            "show me the worst messages this week",
        ],
        "Spot checks": [
            "show me 5 messages the AI wrongly flagged",
            "find chats with the word noob",
            "audit user lery28",
        ],
    }
    for group, qs in example_groups.items():
        with st.expander(group, expanded=(group == "Counts")):
            for q in qs:
                if st.button(q, key=f"ex_{q[:30]}", use_container_width=True):
                    st.session_state.pending_user_input = q
                    st.rerun()

    st.divider()
    st.caption(f"Model: `{ACTIVE_MODEL}`")
    st.caption(f"Index: `{INDEX_NAME}`")


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.title("Moderator chat")
active_title = st.session_state.active_convo_title or "New conversation"
st.caption(f"Active: **{active_title}**  ·  Ask anything in plain English. Click ▶ on a reply to see how the AI answered.")


# ---------------------------------------------------------------------------
# Render existing conversation
# ---------------------------------------------------------------------------

for msg in st.session_state.messages:
    role = msg["role"]
    with st.chat_message(role):
        st.markdown(msg["content"])
        trace = msg.get("trace")
        if trace:
            with st.expander("How the AI answered this"):
                st.markdown(f"**Step 1 — chose tool:** `{trace.get('tool', '?')}`")
                if trace.get("params"):
                    st.code(json.dumps(trace["params"], indent=2), language="json")
                if trace.get("raw_result"):
                    st.markdown("**Step 2 — raw data from the database:**")
                    st.code(trace["raw_result"][:4000])
                if trace.get("latency_total_s"):
                    st.caption(f"Total AI thinking time: {trace['latency_total_s']:.1f}s")


# ---------------------------------------------------------------------------
# Handle input
# ---------------------------------------------------------------------------

pending = st.session_state.pop("pending_user_input", None)
user_input = st.chat_input("Ask the moderation AI anything…") or pending

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})

    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        trace_holder = st.expander("How the AI is answering (live)", expanded=True)

        import time
        t0 = time.time()

        with trace_holder:
            st.markdown("**Step 1** — figuring out what kind of question this is…")
        router_prompt = build_leader_router_prompt(user_input, st.session_state.schema)
        params = ollama_chat_json(router_prompt)

        if params is None:
            reply = "I couldn't parse that. Try rephrasing — maybe more direct? (e.g. 'how many false positives' or 'top users from twitch')"
            trace = {"tool": "ROUTER_FAILED", "params": None, "raw_result": None,
                     "latency_total_s": time.time() - t0}
            placeholder.markdown(reply)
            with trace_holder:
                st.error("Couldn't decide which tool to use.")
        else:
            tool = params.get("tool")
            with trace_holder:
                st.markdown(f"Decided to use: **`{tool}`**")
                st.code(json.dumps(params, indent=2), language="json")

            if tool == "DIRECT_MESSAGE":
                reply = params.get("message", "Hi! Ask me about your records — how many, who's toxic, show me false positives, etc.")
                trace = {"tool": tool, "params": params, "raw_result": reply,
                         "latency_total_s": time.time() - t0}
                placeholder.markdown(reply)
                with trace_holder:
                    st.info("No database query needed — just a conversational reply.")

            elif tool in TOOL_REGISTRY:
                with trace_holder:
                    st.markdown("**Step 2** — querying the database…")
                try:
                    raw_result = TOOL_REGISTRY[tool](params)
                except Exception as exc:
                    raw_result = f"Database query failed: {exc}"

                with trace_holder:
                    st.markdown("**Database returned:**")
                    st.code(str(raw_result)[:4000])
                    st.markdown("**Step 3** — writing a friendly reply…")

                synthesis_prompt = build_leader_synthesis_prompt(user_input, str(raw_result))
                reply = ollama_chat_text(synthesis_prompt)

                trace = {"tool": tool, "params": params, "raw_result": str(raw_result),
                         "latency_total_s": time.time() - t0}
                placeholder.markdown(reply)

            else:
                reply = f"The AI suggested using a tool I don't have: `{tool}`. Try rephrasing the question."
                trace = {"tool": tool, "params": params, "raw_result": None,
                         "latency_total_s": time.time() - t0}
                placeholder.markdown(reply)
                with trace_holder:
                    st.warning(f"Unknown tool: {tool}")

        st.session_state.messages.append({
            "role": "assistant",
            "content": reply,
            "trace": trace,
        })

        # Persist the conversation after each turn.
        save_active_conversation()

    st.rerun()


# ---------------------------------------------------------------------------
# Empty-state hint
# ---------------------------------------------------------------------------

if not st.session_state.messages:
    st.info(
        "👋 Start by clicking a suggested question in the sidebar, or just type below.\n\n"
        "You can ask things like:\n"
        "- *how many records were checked by the AI?*\n"
        "- *who are the most toxic users?*\n"
        "- *show me messages the AI wrongly flagged*\n"
        "- *audit user lery28*\n\n"
        "No need to use technical terms — talk normally."
    )
