"""Ollama /api/chat with Gemma 4–style native audio.

For Gemma 4 on Ollama, audio is passed as base64 **in the ``images`` array** (not ``audio``).
Upload bytes are forwarded unchanged from the client (often WebM/Opus); whether Ollama treats them
as speech depends on your model/runtime — see upstream Gemma/Ollama docs.

Configure overrides with ``OLLAMA_NATIVE_AUDIO_STYLE``: ``images`` (default), ``string``, ``array``, ``both``.
"""

from __future__ import annotations

import logging
import os
from typing import Any, List, Sequence

import httpx
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_ollama import ChatOllama
from langchain_ollama.chat_models import _get_tool_calls_from_response

logger = logging.getLogger(__name__)


def _patch_user_message_audio(msg: dict[str, Any], audio_base64: str) -> dict[str, Any]:
    style = os.getenv("OLLAMA_NATIVE_AUDIO_STYLE", "images").strip().lower()
    if style not in ("images", "string", "array", "both"):
        logger.warning("Unknown OLLAMA_NATIVE_AUDIO_STYLE=%r; using images.", style)
        style = "images"

    scalar_key = (os.getenv("OLLAMA_NATIVE_AUDIO_FIELD", "audio") or "audio").strip() or "audio"
    array_key = (os.getenv("OLLAMA_NATIVE_AUDIO_ARRAY_FIELD", "audios") or "audios").strip() or "audios"

    base = dict(msg)
    role = base.get("role", "user")
    content = base.get("content") or ""

    if style == "images":
        existing = base.get("images")
        imgs: list[str] = []
        if isinstance(existing, list):
            imgs = [x for x in existing if isinstance(x, str) and x]
        imgs.append(audio_base64)
        out: dict[str, Any] = {"role": role, "images": imgs, "content": content}
        for k in ("tool_calls", "tool_call_id"):
            if k in base:
                out[k] = base[k]
        return out

    out = dict(base)
    if style in ("string", "both"):
        out[scalar_key] = audio_base64
    if style in ("array", "both"):
        out[array_key] = [audio_base64]

    # If we are using a dedicated audio field, remove 'images' to avoid
    # triggering Ollama's vision decoder which might error on audio data.
    if style != "images" and "images" in out:
        del out["images"]

    logger.debug(
        "Native Ollama audio patch style=%s keys=%s",
        style,
        [k for k in out if k in (scalar_key, array_key)],
    )
    return out


async def invoke_ollama_with_native_audio(
    base_llm: ChatOllama,
    lc_messages: Sequence[BaseMessage],
    tools: List,
    *,
    audio_base64: str,
) -> AIMessage:
    """Call Ollama JSON /api/chat with tools, attaching native audio on the latest user message."""
    formatted_tools = [convert_to_openai_tool(t) for t in tools]
    chat_params = base_llm._chat_params(
        list(lc_messages),
        stream=False,
        tools=formatted_tools,
    )
    ollama_messages: list[dict[str, Any]] = list(chat_params.pop("messages"))
    patched = False
    for i in range(len(ollama_messages) - 1, -1, -1):
        if ollama_messages[i].get("role") == "user":
            ollama_messages[i] = _patch_user_message_audio(ollama_messages[i], audio_base64)
            patched = True
            break
    if not patched:
        logger.warning("No user role message to attach native audio; Ollama request may fail.")

    payload = {**chat_params, "messages": ollama_messages, "stream": False}
    base_url = (base_llm.base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
    timeout_sec = float(os.getenv("OLLAMA_NATIVE_AUDIO_TIMEOUT_SEC", "600"))
    timeout = httpx.Timeout(timeout_sec)

    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(f"{base_url}/api/chat", json=payload)
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            detail = ""
            try:
                detail = r.text[:800]
            except Exception:
                pass
            logger.exception("Ollama native-audio chat failed: %s %s", r.status_code, detail)
            raise ValueError(f"Ollama chat failed ({r.status_code}): {detail or r.reason_phrase}") from e

        data = r.json()

    msg = data.get("message") or {}
    content = msg.get("content") or ""
    tool_calls = _get_tool_calls_from_response(data)
    thinking = msg.get("thinking")
    extra: dict[str, Any] = {}
    if thinking:
        extra["reasoning_content"] = thinking
    pe = data.get("prompt_eval_count")
    ev = data.get("eval_count")
    usage_meta = None
    if pe is not None or ev is not None:
        usage_meta = {
            "input_tokens": int(pe or 0),
            "output_tokens": int(ev or 0),
            "total_tokens": int((pe or 0) + (ev or 0)),
        }
    return AIMessage(
        content=content,
        tool_calls=tool_calls,
        usage_metadata=usage_meta,
        additional_kwargs=extra,
    )
