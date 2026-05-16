"""Load all local ML models before the API serves traffic (always, not optional)."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


def preload_all_models_sync() -> None:
    from backend.embedding_util import preload_embedding_model
    from backend.native_audio_llm import preload_hf_model
    from backend.speech import preload_whisper_model

    logger.info("Preloading embedding model…")
    preload_embedding_model()
    logger.info("Preloading Whisper…")
    preload_whisper_model()
    logger.info("Preloading Gemma multimodal model…")
    preload_hf_model()
    assert_models_ready()
    logger.info("All local models preloaded.")


async def preload_all_models() -> None:
    await asyncio.to_thread(preload_all_models_sync)


def models_ready() -> dict[str, bool]:
    from backend.embedding_util import is_embedding_loaded
    from backend.native_audio_llm import is_hf_loaded
    from backend.speech import is_whisper_loaded

    return {
        "embeddings": is_embedding_loaded(),
        "whisper": is_whisper_loaded(),
        "gemma": is_hf_loaded(),
    }


def assert_models_ready() -> None:
    status = models_ready()
    missing = [name for name, ok in status.items() if not ok]
    if missing:
        raise RuntimeError(f"Required models not loaded: {', '.join(missing)}")


def all_models_ready() -> bool:
    return all(models_ready().values())
