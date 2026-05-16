import contextvars
import logging
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Annotated, List, Optional, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from backend.booking_guard import build_workflow_hint, scan_messages_for_session
from backend.language_util import infer_locale_from_messages, reply_language_instruction_block

load_dotenv()
logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_MCP_SERVER_SCRIPT = _PROJECT_ROOT / "backend" / "mcp_server" / "server.py"
MCP_SERVER_NAME = "appointments"

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e2b")
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.2"))

_native_audio_b64_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "native_audio_b64", default=None
)


def use_native_audio_llm() -> bool:
    return os.getenv("USE_NATIVE_AUDIO_LLM", "").lower() in ("1", "true", "yes")


def prime_native_audio_turn(audio_b64: str) -> None:
    _native_audio_b64_ctx.set(audio_b64)


def clear_native_audio_turn() -> None:
    _native_audio_b64_ctx.set(None)


def take_native_audio_payload() -> Optional[str]:
    v = _native_audio_b64_ctx.get(None)
    _native_audio_b64_ctx.set(None)
    return v

_READ_TOOL_NAMES = frozenset({
    "list_doctors",
    "check_doctor_availability",
    "verify_patient",
    "validate_booking",
    "validate_reschedule",
})
_WRITE_TOOL_NAMES = frozenset({"book_appointment", "reschedule_appointment"})

SYSTEM_PROMPT = """You are a clinic receptionist. Use tools for all doctor and schedule facts — never guess.

**Workflow (strict order):**
1. **Discover** — `list_doctors` when they need a doctor; `check_doctor_availability` before any date/time you offer.
2. **Collect** — full name; **phone number only** (at least 7 digits, no email). Pass `contact_info` as a plain string, e.g. `"0529123456"`.
3. **Validate** — call `validate_booking` or `validate_reschedule` with the **same** fields you will write; fix every `Error:` line before proceeding.
4. **Confirm** — short recap, then `book_appointment` or `reschedule_appointment`. The UI asks the patient once; **do not** say the visit is saved until the tool returns success after that confirmation.

**Availability:** Only repeat dates/times from `check_doctor_availability`. Use the calendar section for “next Wednesday” / “20 May” → YYYY-MM-DD. If a write tool returns `Error:`, quote it **verbatim** (never “scheduling conflict”).

**Reschedule:** `verify_patient` → appointment id → availability → `validate_reschedule` → recap → `reschedule_appointment`.

Keep answers short. Do not mention internal tool names to the patient.

## Language (Arabic and English)
- Match the patient’s **latest** human message language (Arabic script vs Latin).
- Translate tool output into that language; doctor names may stay in Latin letters.
- Map Arabic clinical terms to their English tool equivalents (e.g., "حجز موعد" -> book_appointment, "تعديل" -> reschedule_appointment).
- Keep responses short and professional in both languages."""


_mcp_client: Optional[MultiServerMCPClient] = None
_mcp_stack: Optional[AsyncExitStack] = None
tools: List = []
read_tool_node = None
write_tool_node = None
base_chat_ollama: Optional[ChatOllama] = None
llm = None
_compiled_graph = None


def _mcp_stdio_connection() -> dict:
    import sys
    return {
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-m", "backend.mcp_server.server"],
        "cwd": str(_PROJECT_ROOT),
    }


async def init_agent_mcp() -> None:
    global _mcp_client, _mcp_stack, tools, base_chat_ollama, llm, read_tool_node, write_tool_node, _compiled_graph

    await shutdown_agent_mcp()
    _mcp_client = MultiServerMCPClient({MCP_SERVER_NAME: _mcp_stdio_connection()})
    stack = AsyncExitStack()
    session = await stack.enter_async_context(_mcp_client.session(MCP_SERVER_NAME))
    tools[:] = await load_mcp_tools(session, server_name=MCP_SERVER_NAME)
    logger.info("MCP tools: %s", [getattr(t, "name", "?") for t in tools])

    read_tools = [t for t in tools if getattr(t, "name", None) in _READ_TOOL_NAMES]
    write_tools = [t for t in tools if getattr(t, "name", None) in _WRITE_TOOL_NAMES]
    read_tool_node = ToolNode(read_tools)
    write_tool_node = ToolNode(write_tools)

    base_chat_ollama = ChatOllama(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=OLLAMA_TEMPERATURE,
    )
    llm = base_chat_ollama.bind_tools(tools)
    _compiled_graph = build_graph()
    _mcp_stack = stack


async def shutdown_agent_mcp() -> None:
    global _mcp_client, _mcp_stack, tools, base_chat_ollama, llm, read_tool_node, write_tool_node, _compiled_graph
    if _mcp_stack is not None:
        try:
            await _mcp_stack.aclose()
        except Exception as e:
            logger.warning("MCP shutdown: %s", e)
        _mcp_stack = None
    _mcp_client = None
    tools.clear()
    base_chat_ollama = None
    llm = None
    clear_native_audio_turn()
    read_tool_node = None
    write_tool_node = None
    _compiled_graph = None


def get_graph():
    if _compiled_graph is None:
        raise RuntimeError("Graph not initialized; call init_agent_mcp() at startup.")
    return _compiled_graph


class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    workflow_hint: str
    last_doctor_id: Optional[int]


def _latest_human_text(messages: list) -> str:
    for msg in reversed(messages or []):
        if isinstance(msg, HumanMessage):
            c = msg.content
            if isinstance(c, str) and c.strip():
                return c.strip()
    return ""


async def prepare_context_node(state: AgentState):
    from datetime import datetime, timedelta

    now = datetime.now()
    today = now.date()
    iso_today = today.isoformat()
    weekday = today.strftime("%A")
    iso_tomorrow = (today + timedelta(days=1)).isoformat()
    human = now.strftime("%A %B %d, %Y %I:%M %p")

    latest = _latest_human_text(state["messages"])
    locale = infer_locale_from_messages(state["messages"])
    snap = scan_messages_for_session(state["messages"], latest)
    hint = build_workflow_hint(snap, locale)

    date_context = (
        "\n## Server date (authoritative)\n"
        f"- **Today (ISO):** `{iso_today}` — **{weekday}**\n"
        f"- **Local time:** {human}\n"
        f"- **Tomorrow:** `{iso_tomorrow}`\n"
        f"- **Year when omitted:** {today.year}\n"
    )

    return {
        "workflow_hint": date_context + hint,
        "last_doctor_id": snap.last_doctor_id,
    }


async def after_read_node(state: AgentState):
    from datetime import datetime, timedelta

    now = datetime.now()
    today = now.date()
    date_context = (
        "\n## Server date (authoritative)\n"
        f"- **Today (ISO):** `{today.isoformat()}` — **{today.strftime('%A')}**\n"
        f"- **Local time:** {now.strftime('%A %B %d, %Y %I:%M %p')}\n"
    )
    latest = _latest_human_text(state["messages"])
    locale = infer_locale_from_messages(state["messages"])
    snap = scan_messages_for_session(state["messages"], latest)
    return {
        "last_doctor_id": snap.last_doctor_id,
        "workflow_hint": date_context + build_workflow_hint(snap, locale),
    }


async def agent_node(state: AgentState):
    locale = infer_locale_from_messages(state["messages"])
    lang_context = reply_language_instruction_block(locale)
    workflow_hint = state.get("workflow_hint") or ""

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT + workflow_hint + lang_context),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )
    prompt_val = await prompt.ainvoke({"messages": state["messages"]})
    lc_msgs = prompt_val.to_messages()

    audio_b64 = take_native_audio_payload()
    if audio_b64:
        if base_chat_ollama is None:
            raise RuntimeError("Native audio requires base ChatOllama instance.")
        from backend.native_audio_llm import invoke_ollama_with_native_audio

        out = await invoke_ollama_with_native_audio(
            base_chat_ollama,
            lc_msgs,
            tools,
            audio_base64=audio_b64,
        )
    else:
        out = await llm.ainvoke(lc_msgs)

    return {"messages": [out]}


def should_continue(state: AgentState) -> str:
    last = state["messages"][-1]
    tcs = getattr(last, "tool_calls", None) or []
    if not tcs:
        return END
    tc0 = tcs[0]
    name = tc0.get("name") if isinstance(tc0, dict) else getattr(tc0, "name", None)
    if name in _WRITE_TOOL_NAMES:
        return "write_tools"
    if name in _READ_TOOL_NAMES:
        return "read_tools"
    return END


def build_graph():
    if llm is None or read_tool_node is None or write_tool_node is None:
        raise RuntimeError("LLM/tools not ready.")

    g = StateGraph(AgentState)
    g.add_node("prepare_context", prepare_context_node)
    g.add_node("agent", agent_node)
    g.add_node("read_tools", read_tool_node)
    g.add_node("after_read", after_read_node)
    g.add_node("write_tools", write_tool_node)
    g.set_entry_point("prepare_context")
    g.add_edge("prepare_context", "agent")
    g.add_conditional_edges(
        "agent",
        should_continue,
        {"read_tools": "read_tools", "write_tools": "write_tools", END: END},
    )
    g.add_edge("read_tools", "after_read")
    g.add_edge("after_read", "agent")
    g.add_edge("write_tools", "agent")
    return g.compile(checkpointer=MemorySaver(), interrupt_before=["write_tools"])
