"""Speech-to-text (faster-whisper) and text-to-speech (edge-tts) for AR/EN."""

from __future__ import annotations

import asyncio
import io
import logging
import os
import tempfile
from functools import lru_cache
from typing import Optional

from backend.language_util import Locale, infer_locale_from_text

logger = logging.getLogger(__name__)

VOICES: dict[Locale, str] = {
    "en": os.getenv("TTS_VOICE_EN", "en-US-JennyNeural"),
    "ar": os.getenv("TTS_VOICE_AR", "ar-SA-ZariyahNeural"),
}

_whisper_model = None
_model_lock = asyncio.Lock()


@lru_cache(maxsize=1)
def _whisper_settings() -> tuple[str, str, str]:
    return (
        os.getenv("WHISPER_MODEL", "base"),
        os.getenv("WHISPER_DEVICE", "cpu"),
        os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
    )


def is_whisper_loaded() -> bool:
    return _whisper_model is not None


def preload_whisper_model() -> None:
    """Load Whisper at startup (required)."""
    _load_whisper()


def _load_whisper():
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    from faster_whisper import WhisperModel

    model_size, device, compute_type = _whisper_settings()
    logger.info("Loading Whisper model=%s device=%s", model_size, device)
    _whisper_model = WhisperModel(model_size, device=device, compute_type=compute_type)
    return _whisper_model


def _locale_to_whisper_lang(locale: Optional[str]) -> Optional[str]:
    if locale in ("ar", "en"):
        return locale
    return None


def transcribe_audio(audio_bytes: bytes, hint_locale: Optional[str] = None) -> tuple[str, Locale]:
    if not audio_bytes:
        raise ValueError("Empty audio payload")

    max_bytes = int(os.getenv("SPEECH_MAX_AUDIO_BYTES", str(15 * 1024 * 1024)))
    if len(audio_bytes) > max_bytes:
        raise ValueError("Audio file is too large")

    if _whisper_model is None:
        raise RuntimeError(
            "Whisper is not loaded. Startup preload must run before transcribe_audio."
        )
    model = _whisper_model

    # Use hint_locale to provide a soft prompt instead of forcing the language.
    # This allows Whisper to still detect a language switch (e.g. from AR to EN).
    prompt = None
    if hint_locale == "ar":
        prompt = "محادثة باللغة العربية"
    elif hint_locale == "en":
        prompt = "English conversation"

    with tempfile.NamedTemporaryFile(suffix=".webm", delete=True) as tmp:
        tmp.write(audio_bytes)
        tmp.flush()
        segments, info = model.transcribe(
            tmp.name,
            language=None, # Allow auto-detection for fluid switching
            initial_prompt=prompt,
            beam_size=7,   # Increased for better accuracy
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=800), # Relaxed VAD
        )
        text = " ".join(s.text.strip() for s in segments if s.text.strip()).strip()

    if not text:
        raise ValueError("Could not understand the audio — please try again")

    detected = getattr(info, "language", None)
    if detected in ("ar", "en"):
        locale: Locale = detected  # type: ignore[assignment]
    else:
        locale = infer_locale_from_text(text)
    return text, locale


async def transcribe_audio_async(
    audio_bytes: bytes, hint_locale: Optional[str] = None
) -> tuple[str, Locale]:
    async with _model_lock:
        return await asyncio.to_thread(transcribe_audio, audio_bytes, hint_locale)


async def _synthesize_with_voice(cleaned: str, voice: str) -> bytes:
    import edge_tts

    communicate = edge_tts.Communicate(cleaned, voice)
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    data = buf.getvalue()
    if not data:
        raise ValueError("TTS produced no audio")
    return data


async def synthesize_speech(text: str, locale: Locale) -> bytes:
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("Nothing to speak")

    primary = VOICES.get(locale, VOICES["en"])
    fallback = VOICES["ar"] if locale == "en" else VOICES["en"]
    try:
        return await _synthesize_with_voice(cleaned, primary)
    except Exception as e:
        logger.warning("TTS failed for locale=%s, retrying fallback voice: %s", locale, e)
        return await _synthesize_with_voice(cleaned, fallback)
