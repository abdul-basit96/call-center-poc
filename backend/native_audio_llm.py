"""Hugging Face Gemma 4 inference (text + native audio) with tool calling."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from typing import Any, List, Optional, Sequence

import numpy as np
import torch
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_huggingface.chat_models.huggingface import _convert_message_to_dict

from backend.audio_util import decode_audio_bytes_to_mono_16k

try:
    from transformers import AutoModelForMultimodalLM, AutoProcessor

    HAS_HF = True
except ImportError:
    HAS_HF = False

logger = logging.getLogger(__name__)

_HF_MODEL = None
_HF_PROCESSOR = None
_HF_DEVICE: Optional[str] = None

_TOOL_CALL_CLOSE = "<tool_call|>"
_GEMMA_STR_DELIM = '<|"|>'
_TOOL_CALL_RE = re.compile(
    r"<\|tool_call>call:(?P<name>[^{]+)\{(?P<args>.*?)\}(?:<tool_call\|>|$)",
    re.DOTALL,
)
# Gemma 4 chat-template control tokens (kept in decode for tool parsing; strip for UI).
_GEMMA_CONTROL_TOKEN_RE = re.compile(
    r"(?:<\|turn\|>|<turn\|>|<\|turn>)"
    r"|(?:<\|start_of_turn\|>|<\|end_of_turn\|>)"
    r"|<\|channel\|>"
    r"|(?:<\|tool_response\|>|<tool_response\|>|<\|tool_response>)"
    r"|(?:<\|tool_call\|>|<tool_call\|>)"
    r"|<eos>"
)


def _model_id() -> str:
    return os.getenv("HF_NATIVE_MODEL_ID", "google/gemma-4-E2B-it")


def _max_new_tokens() -> int:
    return int(os.getenv("HF_MAX_NEW_TOKENS", "512"))


def _inference_device() -> str:
    """Pick a single device. Avoid device_map='auto' off CUDA (meta-tensor errors on Mac/CPU)."""
    forced = (os.getenv("HF_DEVICE") or "").strip().lower()
    if forced in ("cpu", "cuda", "mps"):
        return forced
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        use_mps = os.getenv("HF_USE_MPS", "true").lower() in ("1", "true", "yes")
        if use_mps:
            return "mps"
    return "cpu"


def _load_dtype(device: str) -> torch.dtype:
    if device == "cuda":
        return torch.bfloat16
    if device == "mps":
        return torch.float16
    return torch.float32


def _model_input_device(model: torch.nn.Module) -> torch.device:
    global _HF_DEVICE
    if _HF_DEVICE:
        return torch.device(_HF_DEVICE)
    try:
        return next(model.parameters()).device
    except StopIteration:
        return torch.device("cpu")


def _move_inputs_to_model(
    inputs: dict[str, Any],
    model: torch.nn.Module,
) -> dict[str, Any]:
    device = _model_input_device(model)
    dtype = getattr(model, "dtype", None) or _load_dtype(str(device).split(":")[0])
    out: dict[str, Any] = {}
    for key, value in inputs.items():
        if not hasattr(value, "to"):
            out[key] = value
            continue
        if value.is_floating_point():
            out[key] = value.to(device=device, dtype=dtype)
        else:
            out[key] = value.to(device=device)
    return out


def _load_hf_native():
    global _HF_MODEL, _HF_PROCESSOR, _HF_DEVICE
    if not HAS_HF:
        raise ImportError(
            "Hugging Face dependencies (transformers, torch) are not installed."
        )
    if _HF_MODEL is not None:
        return _HF_MODEL, _HF_PROCESSOR

    model_id = _model_id()
    token = os.getenv("HF_TOKEN") or None
    device = _inference_device()
    dtype = _load_dtype(device)
    attn = os.getenv("HF_ATTN_IMPLEMENTATION", "sdpa")
    logger.info("Loading HF model: %s (device=%s, dtype=%s)", model_id, device, dtype)
    _HF_PROCESSOR = AutoProcessor.from_pretrained(model_id, token=token)
    load_kw: dict[str, Any] = {
        "token": token,
        "torch_dtype": dtype,
        "attn_implementation": attn,
        "low_cpu_mem_usage": False,
    }
    if device == "cuda":
        load_kw["device_map"] = "auto"
        load_kw["low_cpu_mem_usage"] = True
        _HF_MODEL = AutoModelForMultimodalLM.from_pretrained(model_id, **load_kw)
    else:
        _HF_MODEL = AutoModelForMultimodalLM.from_pretrained(model_id, **load_kw)
        _HF_MODEL = _HF_MODEL.to(device)
    _HF_MODEL.eval()
    _HF_DEVICE = device
    logger.info("HF model ready on %s", _model_input_device(_HF_MODEL))
    return _HF_MODEL, _HF_PROCESSOR



def is_hf_loaded() -> bool:
    return _HF_MODEL is not None and _HF_PROCESSOR is not None


def preload_hf_model() -> None:
    """Load model weights at startup (required)."""
    _load_hf_native()


def _require_hf_native():
    if not is_hf_loaded():
        raise RuntimeError(
            "HF Gemma model is not loaded. Startup preload must run before inference."
        )
    return _HF_MODEL, _HF_PROCESSOR


def _prepare_audio_array(audio_bytes: bytes) -> np.ndarray:
    # Browser voice sends WebM/Opus; librosa cannot read that from BytesIO alone.
    return decode_audio_bytes_to_mono_16k(audio_bytes, filename_hint="recording.webm")


def _formatted_tools(tools: List) -> list[dict[str, Any]]:
    return [convert_to_openai_tool(t) for t in tools]


def _lc_messages_to_hf(lc_messages: Sequence[BaseMessage]) -> list[dict[str, Any]]:
    """Convert LangChain messages for Gemma's chat template (incl. tool name)."""
    out: list[dict[str, Any]] = []
    for m in lc_messages:
        d = _convert_message_to_dict(m)
        if isinstance(m, AIMessage) and m.tool_calls:
            d["content"] = ""
        if isinstance(m, ToolMessage) and getattr(m, "name", None) and "name" not in d:
            d["name"] = m.name
        out.append(d)
    return out


def _strip_audio_token_from_text(text: str, audio_token: str) -> str:
    """Avoid duplicating <|audio|> in text when content also has an audio block."""
    if not text:
        return text
    escaped = re.escape(audio_token)
    cleaned = re.sub(rf"\s*{escaped}\s*", "\n", text)
    return re.sub(r"\n{2,}", "\n", cleaned).strip()


def _normalize_audio_placeholders(prompt: str, audio_token: str, num_clips: int) -> str:
    """Gemma's processor requires one <|audio|> per waveform; extras raise StopIteration."""
    if num_clips <= 0:
        return prompt
    escaped = re.escape(audio_token)
    without = re.sub(escaped, "", prompt)
    block = "".join([audio_token] * num_clips)
    for marker in ("<turn|>", "<|turn|>"):
        idx = without.rfind(marker)
        if idx != -1:
            return without[:idx].rstrip() + "\n" + block + without[idx:]
    return without.rstrip() + "\n" + block


def _patch_last_user_with_audio(
    messages: list[dict[str, Any]],
    *,
    audio: np.ndarray,
    fallback_text: str,
    audio_token: str,
) -> None:
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") != "user":
            continue
        text = fallback_text
        content = messages[i].get("content")
        if isinstance(content, str) and content.strip():
            text = _strip_audio_token_from_text(content.strip(), audio_token)
        messages[i]["content"] = [
            {"type": "text", "text": text or fallback_text},
            {"type": "audio", "audio": audio},
        ]
        return
    messages.append(
        {
            "role": "user",
            "content": [
                {"type": "text", "text": fallback_text},
                {"type": "audio", "audio": audio},
            ],
        }
    )


def _processor_inputs_dict(batch: Any) -> dict[str, Any]:
    if isinstance(batch, dict):
        return batch
    data = getattr(batch, "data", None)
    if isinstance(data, dict):
        return data
    raise TypeError(f"Unexpected processor output type: {type(batch)!r}")


def _has_audio_features(inputs: dict[str, Any]) -> bool:
    for key in inputs:
        kl = key.lower()
        if "audio" in kl or kl in ("input_features", "input_features_mask"):
            return True
    return False


def _split_top_level(s: str, sep: str = ",") -> list[str]:
    parts: list[str] = []
    depth = 0
    in_string = False
    start = 0
    i = 0
    while i < len(s):
        ch = s[i]
        if in_string:
            if s.startswith(_GEMMA_STR_DELIM, i):
                in_string = False
                i += len(_GEMMA_STR_DELIM)
                continue
            i += 1
            continue
        if s.startswith(_GEMMA_STR_DELIM, i):
            in_string = True
            i += len(_GEMMA_STR_DELIM)
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        elif ch == sep and depth == 0:
            parts.append(s[start:i].strip())
            start = i + 1
        i += 1
    tail = s[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _parse_gemma4_value(raw: str) -> Any:
    val = raw.strip()
    if not val:
        return ""
    if val.startswith(_GEMMA_STR_DELIM):
        end = val.find(_GEMMA_STR_DELIM, len(_GEMMA_STR_DELIM))
        if end == -1:
            return val[len(_GEMMA_STR_DELIM) :]
        return val[len(_GEMMA_STR_DELIM) : end]
    if val == "true":
        return True
    if val == "false":
        return False
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        return [_parse_gemma4_value(p) for p in _split_top_level(inner)]
    if val.startswith("{") and val.endswith("}"):
        return _parse_gemma4_args(val[1:-1])
    try:
        if "." in val:
            return float(val)
        return int(val)
    except ValueError:
        return val


def _parse_gemma4_args(args_str: str) -> dict[str, Any]:
    args_str = args_str.strip()
    if not args_str:
        return {}
    out: dict[str, Any] = {}
    for part in _split_top_level(args_str):
        if not part:
            continue
        colon = part.find(":")
        if colon == -1:
            continue
        key = part[:colon].strip()
        value = part[colon + 1 :].strip()
        out[key] = _parse_gemma4_value(value)
    return out


def strip_gemma_control_tokens(text: str) -> str:
    """Remove template markup from text shown to the patient."""
    if not text:
        return ""
    t = re.sub(r"<\|channel>thought[\s\S]*?<\|channel\|>", "", text)
    t = _GEMMA_CONTROL_TOKEN_RE.sub("", t)
    t = re.sub(r"^(?:model|user)\s*\n+", "", t, flags=re.IGNORECASE)
    return t.strip()


def _parse_gemma4_tool_calls(text: str) -> tuple[str, list[dict[str, Any]]]:
    tool_calls: list[dict[str, Any]] = []
    content_parts: list[str] = []
    last_end = 0
    for match in _TOOL_CALL_RE.finditer(text):
        content_parts.append(text[last_end : match.start()])
        name = match.group("name").strip()
        args_raw = match.group("args")
        try:
            args = _parse_gemma4_args(args_raw)
        except Exception as e:
            logger.warning("Could not parse tool args for %s: %s", name, e)
            args = {}
        tool_calls.append(
            {
                "name": name,
                "args": args,
                "id": str(uuid.uuid4()),
                "type": "tool_call",
            }
        )
        last_end = match.end()
    content_parts.append(text[last_end:])
    content = strip_gemma_control_tokens("".join(content_parts))
    return content, tool_calls


def _response_to_aimessage(decoded: str) -> AIMessage:
    content, tool_calls = _parse_gemma4_tool_calls(decoded)
    extra: dict[str, Any] = {}
    if decoded and decoded != content:
        extra["raw_generation"] = decoded
    # Gemma's template appends assistant text *after* <|tool_response|>. Non-empty content
    # there makes the next turn emit only <eos> instead of summarizing tool results.
    if tool_calls:
        if content:
            extra["pre_tool_text"] = content
        content = ""
    return AIMessage(content=content or "", tool_calls=tool_calls, additional_kwargs=extra)


def _generate_sync(
    lc_messages: Sequence[BaseMessage],
    tools: List,
    *,
    audio_bytes: Optional[bytes],
) -> AIMessage:
    model, processor = _require_hf_native()
    hf_tools = _formatted_tools(tools)
    messages = _lc_messages_to_hf(lc_messages)

    if audio_bytes is not None:
        audio = _prepare_audio_array(audio_bytes)
        audio_token = getattr(processor, "audio_token", None) or "<|audio|>"
        fallback = "Listen to the patient's request in the audio."
        for msg in reversed(messages):
            if msg.get("role") == "user":
                c = msg.get("content")
                if isinstance(c, str) and c.strip():
                    fallback = c.strip()
                break
        _patch_last_user_with_audio(
            messages,
            audio=audio,
            fallback_text=fallback,
            audio_token=audio_token,
        )
        # tools + tokenize=True drops audio tensors; build prompt then pass waveform to processor.
        prompt = processor.apply_chat_template(
            messages,
            tools=hf_tools,
            tokenize=False,
            add_generation_prompt=True,
        )
        prompt = _normalize_audio_placeholders(prompt, audio_token, num_clips=1)
        batch = processor(
            text=prompt,
            audio=[audio],
            return_tensors="pt",
            padding=True,
        )
        inputs = _processor_inputs_dict(batch)
        if not _has_audio_features(inputs):
            logger.error(
                "Native audio missing in model inputs (keys=%s); model may only see text.",
                list(inputs.keys()),
            )
            raise RuntimeError(
                "Audio could not be encoded for the model. Check Gemma processor / audio setup."
            )
        logger.info("Native audio encoded for inference (keys=%s)", list(inputs.keys()))
    else:
        inputs = processor.apply_chat_template(
            messages,
            tools=hf_tools,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        )

    inputs = _move_inputs_to_model(inputs, model)
    input_len = inputs["input_ids"].shape[-1]

    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=_max_new_tokens(),
            do_sample=False,
        )

    decoded = processor.decode(
        output_ids[0, input_len:],
        skip_special_tokens=False,
    )
    logger.info("HF generation (tools=%s): %s", bool(hf_tools), decoded[:500])
    return _response_to_aimessage(decoded)


async def invoke_hf_chat(
    lc_messages: Sequence[BaseMessage],
    tools: List,
    *,
    audio_bytes: Optional[bytes] = None,
) -> AIMessage:
    """Run Gemma 4 on Hugging Face (text and/or native audio) with MCP tools."""
    try:
        return await asyncio.to_thread(
            _generate_sync,
            lc_messages,
            tools,
            audio_bytes=audio_bytes,
        )
    except StopIteration as e:
        raise RuntimeError(
            "Audio prompt placeholders did not match the number of waveforms. "
            "This is usually caused by duplicate <|audio|> tokens in the chat template."
        ) from e


async def invoke_hf_native_audio(
    lc_messages: Sequence[BaseMessage],
    tools: List,
    *,
    audio_bytes: bytes,
) -> AIMessage:
    return await invoke_hf_chat(lc_messages, tools, audio_bytes=audio_bytes)


async def invoke_hf_text(
    lc_messages: Sequence[BaseMessage],
    tools: List,
) -> AIMessage:
    return await invoke_hf_chat(lc_messages, tools, audio_bytes=None)
