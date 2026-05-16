import json
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from typing import Any, Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage
from pydantic import BaseModel

from backend.agent import (
    clear_native_audio_turn,
    get_graph,
    init_agent_mcp,
    prime_native_audio_turn,
    shutdown_agent_mcp,
    use_native_audio_llm,
)
from backend.booking_guard import (
    booking_stage_label,
    format_validation_reply,
    normalize_tool_args,
    scan_messages_for_session,
    stringify_message_content,
    tool_result_indicates_success,
    validate_write_tool,
)
from backend.language_util import (
    Locale,
    book_confirmation_summary,
    canned_cancel_response,
    fallback_assistant_reply,
    human_text,
    infer_locale_from_messages,
    infer_locale_from_text,
    reschedule_confirmation_summary,
)
from backend.speech import synthesize_speech, transcribe_audio_async

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_DEFAULT_NATIVE_USER_TEXT = (
    "The patient spoke in the attached audio. Listen and respond as the clinic receptionist; "
    "use tools for schedules and bookings."
)


def _human_message_for_native_audio(hint_locale_form: Optional[str]) -> HumanMessage:
    hl = (hint_locale_form or "").strip().lower()
    content = (
        os.getenv(
            "HF_NATIVE_AUDIO_USER_CONTENT",
            # Deprecated alias from Ollama era; kept so existing .env files still work.
            os.getenv("OLLAMA_NATIVE_AUDIO_USER_CONTENT", _DEFAULT_NATIVE_USER_TEXT),
        ).strip()
        or _DEFAULT_NATIVE_USER_TEXT
    )
    if hl in ("ar", "en"):
        return HumanMessage(content=content, additional_kwargs={"voice_hint_locale": hl})
    return HumanMessage(content=content)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting MCP, preloading models, and agent graph…")
    await init_agent_mcp()
    yield
    logger.info("Shutting down MCP…")
    await shutdown_agent_mcp()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    thread_id: str
    status: str = "active"
    pending_confirmation: Optional[Literal["book", "reschedule"]] = None
    confirmation_summary: Optional[str] = None
    reply_locale: Locale = "en"
    validation_errors: Optional[list[str]] = None
    booking_stage: Optional[str] = None
    action_succeeded: Optional[bool] = None


class TranscribeResponse(BaseModel):
    text: str
    locale: Locale


class SynthesizeRequest(BaseModel):
    text: str
    locale: Locale = "en"


def _graph_config(thread_id: str) -> dict:
    return {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": int(os.getenv("LANGGRAPH_RECURSION_LIMIT", "40")),
    }


def _stringify_ai_content(content: Any) -> str:
    from backend.native_audio_llm import strip_gemma_control_tokens

    if isinstance(content, str) and content.strip():
        return strip_gemma_control_tokens(content.strip())
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str) and block.strip():
                parts.append(block.strip())
            elif isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text", "")
                if isinstance(t, str) and t.strip():
                    parts.append(t.strip())
        return "\n".join(parts).strip()
    return ""


def response_from_messages(messages: list) -> str:
    for msg in reversed(messages or []):
        if isinstance(msg, AIMessage):
            t = _stringify_ai_content(msg.content)
            if t:
                return t
    for msg in reversed(messages or []):
        if isinstance(msg, ToolMessage):
            c = stringify_message_content(getattr(msg, "content", None))
            if c:
                return c
    return ""


def tool_call_arguments(tc: dict) -> dict:
    if not isinstance(tc, dict):
        tc = dict(tc) if hasattr(tc, "keys") else {}
    args = tc.get("args")
    if isinstance(args, dict):
        return args
    raw = tc.get("arguments")
    if isinstance(raw, str) and raw.strip():
        try:
            p = json.loads(raw)
            return p if isinstance(p, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _is_confirmation(text: str) -> bool:
    raw = (text or "").strip()
    t = raw.lower()
    if not t:
        return False
    if "yes, please confirm" in t:
        return True
    if any(p in t for p in ("go ahead", "confirm", "book it", "sounds good", "that's fine", "looks good")):
        return True
    if bool(re.search(r"\b(yes|yeah|yep|ok|okay|sure|please|proceed)\b", t)):
        return True
    if any(p in raw for p in ("نعم", "موافق", "أؤكد", "أكد", "تأكيد", "احجز", "تم", "أكيد", "حسناً", "حسنا", "صحيح", "تمام", "موافق")):
        return True
    return False


def _is_rejection(text: str) -> bool:
    raw = (text or "").strip()
    t = raw.lower()
    if any(p in t for p in ("don't", "do not", "never mind", "not now", "no thanks")):
        return True
    if bool(re.search(r"\b(no|nope|cancel|stop)\b", t)):
        return True
    if "no, cancel" in t:
        return True
    if any(p in raw for p in ("لا", "إلغاء", "الغاء", "ألغي", "لا أريد", "لا اريد", "ألغي الحجز", "ألغي ذلك", "توقف")):
        return True
    return False


def _find_pending_write_ai(messages: list) -> Optional[AIMessage]:
    for msg in reversed(messages or []):
        if not isinstance(msg, AIMessage) or not msg.tool_calls:
            continue
        tc0 = msg.tool_calls[0]
        name = tc0.get("name") if isinstance(tc0, dict) else getattr(tc0, "name", None)
        if name in ("book_appointment", "reschedule_appointment"):
            return msg
    return None


def _latest_write_tool_result(messages: list) -> tuple[Optional[str], Optional[str]]:
    """Return (tool_name, content) for the most recent write-tool ToolMessage."""
    for msg in reversed(messages or []):
        if not isinstance(msg, ToolMessage):
            continue
        name = getattr(msg, "name", None) or ""
        if name in ("book_appointment", "reschedule_appointment"):
            return name, stringify_message_content(getattr(msg, "content", None))
    return None, None


async def _reject_invalid_pending(
    config: dict,
    pending: AIMessage,
    errors: list[str],
    locale: Locale,
) -> str:
    text = format_validation_reply(errors, locale)
    await get_graph().aupdate_state(
        config,
        {
            "messages": [
                RemoveMessage(id=pending.id),
                AIMessage(content=text),
            ]
        },
    )
    return text


def _latest_human_from_messages(msgs: list) -> str:
    for msg in reversed(msgs or []):
        if isinstance(msg, HumanMessage):
            t = human_text(msg)
            if t:
                return t
    return ""


def _tool_failure_reply(content: str, locale: Locale) -> str:
    if locale == "ar":
        return f"لم يتم الحفظ. يرجى قراءة السبب للمريض ثم التصحيح:\n\n{content.strip()}"
    return f"The appointment was not saved. Please read this to the patient and fix the details:\n\n{content.strip()}"


def _response_after_turn(
    msgs: list,
    thread_id: str,
    user_locale: Locale,
    *,
    graph_waiting: bool = False,
    action_succeeded: Optional[bool] = None,
) -> ChatResponse:
    reply_locale = user_locale
    text = response_from_messages(msgs)

    if action_succeeded is True:
        _tool_name, tool_content = _latest_write_tool_result(msgs)
        if tool_content:
            if reply_locale == "ar":
                text = f"تم الحجز بنجاح.\n\n{tool_content}"
            else:
                text = f"Your appointment is confirmed.\n\n{tool_content}"

    if action_succeeded is False:
        _tool_name, tool_content = _latest_write_tool_result(msgs)
        if tool_content:
            text = _tool_failure_reply(tool_content, reply_locale)
            reply_locale = infer_locale_from_text(text)

    if (text or "").strip():
        reply_locale = infer_locale_from_text(text)

    pending_kind: Optional[str] = None
    summary: Optional[str] = None
    status = "active"

    if graph_waiting:
        pending_ai = _find_pending_write_ai(msgs)
        if pending_ai and pending_ai.tool_calls:
            tc0 = pending_ai.tool_calls[0]
            name = tc0.get("name") if isinstance(tc0, dict) else getattr(tc0, "name", None)
            args = normalize_tool_args(name or "", tool_call_arguments(tc0))
            if name == "book_appointment":
                pending_kind = "book"
                summary = book_confirmation_summary(args, reply_locale)
            elif name == "reschedule_appointment":
                pending_kind = "reschedule"
                summary = reschedule_confirmation_summary(args, reply_locale)
            status = "waiting_for_confirmation"

    if summary and summary.strip() not in (text or ""):
        text = f"{text}\n\n---\n\n{summary}" if text else summary

    snap = scan_messages_for_session(msgs, _latest_human_from_messages(msgs))
    stage = booking_stage_label(snap)

    return ChatResponse(
        response=text or fallback_assistant_reply(reply_locale),
        thread_id=thread_id,
        status=status,
        pending_confirmation=pending_kind,
        confirmation_summary=summary,
        reply_locale=reply_locale,
        booking_stage=stage,
        action_succeeded=action_succeeded,
    )


async def _run_chat_turn(thread_id: str, human: HumanMessage) -> ChatResponse:
    config = _graph_config(thread_id)
    action_succeeded: Optional[bool] = None
    turn_text = human_text(human)

    try:
        snapshot = await get_graph().aget_state(config)
        waiting = bool(snapshot.next and "write_tools" in snapshot.next)
        msgs_before = snapshot.values.get("messages", [])

        if waiting:
            pending = _find_pending_write_ai(msgs_before)
            if pending and pending.tool_calls:
                tc0 = pending.tool_calls[0]
                name = tc0.get("name") if isinstance(tc0, dict) else getattr(tc0, "name", None)
                args = normalize_tool_args(name or "", tool_call_arguments(tc0))
                errors = validate_write_tool(name or "", args)
                locale = infer_locale_from_messages(msgs_before + [human])

                if errors and (_is_confirmation(turn_text) or not _is_rejection(turn_text)):
                    text = await _reject_invalid_pending(config, pending, errors, locale)
                    return ChatResponse(
                        response=text,
                        thread_id=thread_id,
                        status="validation_failed",
                        validation_errors=errors,
                        reply_locale=locale,
                        action_succeeded=False,
                    )

            if _is_confirmation(turn_text):
                await get_graph().ainvoke(None, config=config)
                action_succeeded = None
            elif _is_rejection(turn_text):
                pending = _find_pending_write_ai(msgs_before)
                if pending:
                    _msgs_for_loc = list(msgs_before)
                    _msgs_for_loc.append(human)
                    _loc = infer_locale_from_messages(_msgs_for_loc)
                    _cancel_text = canned_cancel_response(_loc)
                    await get_graph().aupdate_state(
                        config,
                        {
                            "messages": [
                                RemoveMessage(id=pending.id),
                                human,
                                AIMessage(content=_cancel_text),
                            ]
                        },
                    )
                    return ChatResponse(
                        response=_cancel_text,
                        thread_id=thread_id,
                        reply_locale=_loc,
                        action_succeeded=False,
                    )
                await get_graph().ainvoke(
                    {"messages": [human]},
                    config=config,
                )
            else:
                pending = _find_pending_write_ai(msgs_before)
                if pending:
                    await get_graph().aupdate_state(
                        config,
                        {"messages": [RemoveMessage(id=pending.id)]},
                    )
                await get_graph().ainvoke(
                    {"messages": [human]},
                    config=config,
                )
        else:
            await get_graph().ainvoke(
                {"messages": [human]},
                config=config,
            )

        snap2 = await get_graph().aget_state(config)
        msgs = snap2.values.get("messages") or []
        user_locale = infer_locale_from_messages(msgs)
        still_waiting = bool(snap2.next and "write_tools" in snap2.next)

        if still_waiting:
            pending_ai = _find_pending_write_ai(msgs)
            if pending_ai and pending_ai.tool_calls:
                tc0 = pending_ai.tool_calls[0]
                name = tc0.get("name") if isinstance(tc0, dict) else getattr(tc0, "name", None)
                args = normalize_tool_args(name or "", tool_call_arguments(tc0))
                errors = validate_write_tool(name or "", args)
                if errors:
                    text = await _reject_invalid_pending(config, pending_ai, errors, user_locale)
                    return ChatResponse(
                        response=text,
                        thread_id=thread_id,
                        status="validation_failed",
                        validation_errors=errors,
                        reply_locale=user_locale,
                        action_succeeded=False,
                    )

        if waiting and _is_confirmation(turn_text) and not still_waiting:
            tool_name, tool_content = _latest_write_tool_result(msgs)
            if tool_name and tool_content is not None:
                action_succeeded = tool_result_indicates_success(tool_name, tool_content)

        return _response_after_turn(
            msgs,
            thread_id,
            user_locale,
            graph_waiting=still_waiting,
            action_succeeded=action_succeeded,
        )
    except Exception as e:
        logger.exception("Chat error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    thread_id = request.thread_id or str(uuid.uuid4())
    human = HumanMessage(content=request.message)
    return await _run_chat_turn(thread_id, human)


@app.post("/chat/audio", response_model=ChatResponse)
async def chat_audio(
    audio: UploadFile = File(...),
    thread_id: Optional[str] = Form(None),
    hint_locale: Optional[str] = Form(None),
):
    if not use_native_audio_llm():
        raise HTTPException(
            status_code=403,
            detail="Native audio chat is disabled. Set USE_NATIVE_AUDIO_LLM=true and restart the API.",
        )
    raw = await audio.read()
    max_bytes = int(os.getenv("SPEECH_MAX_AUDIO_BYTES", str(15 * 1024 * 1024)))
    if len(raw) > max_bytes:
        raise HTTPException(status_code=400, detail="Audio file is too large")

    import base64

    b64 = base64.standard_b64encode(raw).decode("ascii")
    human = _human_message_for_native_audio(hint_locale)
    prime_native_audio_turn(b64)
    try:
        return await _run_chat_turn(thread_id or str(uuid.uuid4()), human)
    finally:
        clear_native_audio_turn()


@app.post("/speech/transcribe", response_model=TranscribeResponse)
async def speech_transcribe(
    audio: UploadFile = File(...),
    hint_locale: Optional[str] = Form(None),
):
    try:
        raw = await audio.read()
        text, locale = await transcribe_audio_async(raw, hint_locale=hint_locale)
        return TranscribeResponse(text=text, locale=locale)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Transcribe error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/speech/synthesize")
async def speech_synthesize(body: SynthesizeRequest):
    try:
        audio_bytes = await synthesize_speech(body.text, body.locale)
        return Response(content=audio_bytes, media_type="audio/mpeg")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Synthesize error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    from backend.model_preload import all_models_ready, models_ready

    ready = models_ready()
    ok = all_models_ready()
    payload = {
        "status": "ok" if ok else "starting",
        "speech": True,
        "models": ready,
        "models_preloaded": ok,
        "native_audio_llm": use_native_audio_llm(),
        "llm_backend": "huggingface",
        "hf_model_id": os.getenv("HF_NATIVE_MODEL_ID", "google/gemma-4-E2B-it"),
        "embed_model": os.getenv("EMBED_MODEL", "BAAI/bge-m3"),
        "whisper_model": os.getenv("WHISPER_MODEL", "turbo"),
    }
    if not ok:
        return JSONResponse(status_code=503, content=payload)
    return payload


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
